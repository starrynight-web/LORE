'use client';

import React, { useState, useRef, useEffect } from 'react';
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
  Layers, 
  Eye, 
  EyeOff, 
  ChevronLeft, 
  ChevronRight,
  Database,
  ArrowRight,
  Sparkles,
  RefreshCw,
  Info
} from 'lucide-react';
import { api, DocumentPage, Collection } from '@/lib/api';
import { SAMPLE_DEED_BASE64, SAMPLE_MEMO_BASE64 } from '@/lib/sampleDocs';

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

    // Create object URL for preview if image
    if (selectedFile.type.startsWith('image/')) {
      setImagePreviewUrl(URL.createObjectURL(selectedFile));
    } else {
      setImagePreviewUrl(null);
    }

    try {
      const formData = new FormData();
      formData.append('file', selectedFile);
      formData.append('bengali_repair', String(bengaliRepair));
      formData.append('arabic_digits', String(arabicDigits));
      formData.append('save_to_workspace', 'false');

      const data = await api.liveOCR(formData);
      setOcrResult(data);
      setActivePageIndex(0);
    } catch (err: any) {
      console.error("Live OCR failed:", err);
      setErrorMsg(err.message || 'Real-time OCR extraction failed.');
    } finally {
      setIsProcessing(false);
    }
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files[0]) {
      const f = e.target.files[0];
      setFile(f);
      executeLiveOCR(f);
    }
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      const f = e.dataTransfer.files[0];
      setFile(f);
      executeLiveOCR(f);
    }
  };

  const loadSample = (sampleType: 'deed' | 'memo') => {
    let f: File;
    if (sampleType === 'deed') {
      f = dataURLtoFile(SAMPLE_DEED_BASE64, 'unbhumi_land_deed_scan.png');
    } else {
      f = dataURLtoFile(SAMPLE_MEMO_BASE64, 'northstar_security_directive_2026.png');
    }
    setFile(f);
    executeLiveOCR(f);
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

  const currentPage = ocrResult?.pages[activePageIndex] || null;
  const bboxes = currentPage?.bounding_boxes || [];

  return (
    <div className="flex flex-col gap-6 w-full max-w-7xl mx-auto pb-12">
      {/* Top Banner */}
      <div className="bg-gradient-to-r from-slate-900 via-indigo-950/40 to-slate-900 border border-slate-800 rounded-2xl p-6 shadow-xl relative overflow-hidden">
        <div className="absolute top-0 right-0 w-96 h-96 bg-indigo-500/10 rounded-full blur-3xl pointer-events-none" />
        
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 relative z-10">
          <div>
            <div className="flex items-center gap-2.5 mb-2">
              <span className="p-2 rounded-xl bg-indigo-600/20 text-indigo-400 border border-indigo-500/30">
                <Scan className="w-5 h-5" />
              </span>
              <h1 className="text-xl font-bold text-white tracking-wide">Real-Time OCR & Token Spatial Studio</h1>
              <span className="text-[10px] font-bold px-2 py-0.5 rounded-full bg-emerald-500/20 text-emerald-400 border border-emerald-500/30 flex items-center gap-1">
                <Zap className="w-3 h-3" /> SUB-SECOND REALTIME
              </span>
            </div>
            <p className="text-sm text-slate-400 max-w-3xl leading-relaxed">
              Synchronous dual-stream document intelligence pipeline adhering to the <strong className="text-slate-200">UNBhumi OCR Architecture</strong>.
              Rasterizes scans at 300 DPI, projects 0–1000 normalized bounding boxes, repairs visual Bengali graphemes, and indexes immediately into your Governed RAG workspace.
            </p>
          </div>

          {/* Quick Demo Buttons */}
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-xs text-slate-400 font-medium">Quick Test:</span>
            <button
              onClick={() => loadSample('deed')}
              className="px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-xs font-medium text-slate-200 border border-slate-700 transition-all flex items-center gap-1.5 shadow-sm active:scale-95"
            >
              <FileText className="w-3.5 h-3.5 text-amber-400" />
              <span>UNBhumi Deed Scan</span>
            </button>
            <button
              onClick={() => loadSample('memo')}
              className="px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-xs font-medium text-slate-200 border border-slate-700 transition-all flex items-center gap-1.5 shadow-sm active:scale-95"
            >
              <ShieldCheck className="w-3.5 h-3.5 text-indigo-400" />
              <span>Enterprise Memo Scan</span>
            </button>
          </div>
        </div>
      </div>

      {/* Main Drag & Drop / Upload Strip */}
      <div 
        onDragOver={(e) => e.preventDefault()}
        onDrop={handleDrop}
        onClick={() => fileInputRef.current?.click()}
        className={`border-2 border-dashed rounded-2xl p-6 text-center cursor-pointer transition-all ${
          file 
            ? 'border-indigo-500/50 bg-indigo-950/10' 
            : 'border-slate-800 hover:border-slate-700 bg-slate-900/40 hover:bg-slate-900/70'
        }`}
      >
        <input 
          ref={fileInputRef}
          type="file" 
          accept="image/*,application/pdf"
          onChange={handleFileChange}
          className="hidden" 
        />
        <div className="flex flex-col items-center justify-center gap-2">
          <div className="w-12 h-12 rounded-2xl bg-indigo-600/10 text-indigo-400 border border-indigo-500/20 flex items-center justify-center mb-1">
            <Upload className="w-6 h-6" />
          </div>
          <div className="text-sm font-semibold text-white">
            {file ? file.name : "Drag & drop a document scan (PNG, JPG, PDF, TIFF) or click to browse"}
          </div>
          <p className="text-xs text-slate-400">
            {file ? `${(file.size / 1024).toFixed(1)} KB — Ready to extract` : "Processed synchronously in memory; no queuing latency"}
          </p>
        </div>
      </div>

      {errorMsg && (
        <div className="p-4 rounded-xl bg-red-950/40 border border-red-800/60 text-red-300 text-sm flex items-center gap-2">
          <AlertTriangle className="w-4 h-4 flex-shrink-0" />
          <span>{errorMsg}</span>
        </div>
      )}

      {/* Control Bar */}
      <div className="flex flex-wrap items-center justify-between gap-4 bg-slate-900/80 border border-slate-800 rounded-xl p-3 px-4">
        <div className="flex flex-wrap items-center gap-4 text-xs">
          <label className="flex items-center gap-2 cursor-pointer text-slate-300 hover:text-white select-none">
            <input 
              type="checkbox" 
              checked={bengaliRepair} 
              onChange={(e) => {
                setBengaliRepair(e.target.checked);
                if (file) executeLiveOCR(file);
              }}
              className="rounded bg-slate-800 border-slate-700 text-indigo-600 focus:ring-0" 
            />
            <span>Phonetic Unicode Repair (Bengali)</span>
          </label>

          <label className="flex items-center gap-2 cursor-pointer text-slate-300 hover:text-white select-none">
            <input 
              type="checkbox" 
              checked={arabicDigits} 
              onChange={(e) => {
                setArabicDigits(e.target.checked);
                if (file) executeLiveOCR(file);
              }}
              className="rounded bg-slate-800 border-slate-700 text-indigo-600 focus:ring-0" 
            />
            <span>Bangla to Arabic Numerals</span>
          </label>

          <label className="flex items-center gap-2 cursor-pointer text-slate-300 hover:text-white select-none">
            <input 
              type="checkbox" 
              checked={showBoundingBoxes} 
              onChange={(e) => setShowBoundingBoxes(e.target.checked)}
              className="rounded bg-slate-800 border-slate-700 text-indigo-600 focus:ring-0" 
            />
            <span>Show Word Bounding Boxes</span>
          </label>
        </div>

        {ocrResult && (
          <div className="flex items-center gap-3">
            <span className="text-xs px-2.5 py-1 rounded-lg bg-indigo-500/20 text-indigo-300 border border-indigo-500/30 font-mono font-medium flex items-center gap-1">
              <Zap className="w-3.5 h-3.5 text-amber-400" />
              <span>{ocrResult.timings_ms} ms</span>
            </span>
            <span className={`text-xs px-2.5 py-1 rounded-lg font-mono font-semibold border ${
              ocrResult.ocr_confidence >= 0.85
                ? 'bg-emerald-500/20 text-emerald-300 border-emerald-500/30'
                : ocrResult.ocr_confidence >= 0.70
                ? 'bg-amber-500/20 text-amber-300 border-amber-500/30'
                : 'bg-red-500/20 text-red-300 border-red-500/30'
            }`}>
              {(ocrResult.ocr_confidence * 100).toFixed(1)}% Confidence
            </span>
          </div>
        )}
      </div>

      {/* Main Dual Workspace: Canvas (Left) + Text & Metadata (Right) */}
      {isProcessing ? (
        <div className="bg-slate-900/60 border border-slate-800 rounded-2xl p-16 flex flex-col items-center justify-center gap-3 min-h-[420px]">
          <div className="w-10 h-10 border-3 border-indigo-500 border-t-transparent rounded-full animate-spin" />
          <div className="text-base font-semibold text-white">Running Synchronous OCR Engine...</div>
          <p className="text-xs text-slate-400">
            Applying EXIF alignment, 300 DPI rasterization, token spatial extraction, and Bengali phonetic normalization
          </p>
        </div>
      ) : ocrResult && currentPage ? (
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
          {/* Left: Document Visual Preview & Interactive Bounding Boxes */}
          <div className="lg:col-span-7 bg-slate-900 border border-slate-800 rounded-2xl p-4 flex flex-col shadow-xl">
            <div className="flex items-center justify-between pb-3 border-b border-slate-800 mb-3">
              <div className="flex items-center gap-2">
                <Eye className="w-4 h-4 text-indigo-400" />
                <span className="text-xs font-semibold text-slate-300 uppercase tracking-wider">
                  Spatial Visualizer {imagePreviewUrl ? '(Scan Canvas)' : '(PDF Page Layout)'}
                </span>
              </div>

              {ocrResult.page_count > 1 && (
                <div className="flex items-center gap-2">
                  <button 
                    disabled={activePageIndex === 0}
                    onClick={() => setActivePageIndex(p => Math.max(0, p - 1))}
                    className="p-1 rounded bg-slate-800 text-slate-300 hover:text-white disabled:opacity-30"
                  >
                    <ChevronLeft className="w-4 h-4" />
                  </button>
                  <span className="text-xs text-slate-400">
                    Page {activePageIndex + 1} of {ocrResult.page_count}
                  </span>
                  <button 
                    disabled={activePageIndex >= ocrResult.page_count - 1}
                    onClick={() => setActivePageIndex(p => Math.min(ocrResult.page_count - 1, p + 1))}
                    className="p-1 rounded bg-slate-800 text-slate-300 hover:text-white disabled:opacity-30"
                  >
                    <ChevronRight className="w-4 h-4" />
                  </button>
                </div>
              )}
            </div>

            {/* Canvas Viewport */}
            <div 
              ref={canvasContainerRef}
              className="relative w-full rounded-xl overflow-hidden bg-slate-950 flex items-center justify-center min-h-[460px] border border-slate-800/80 p-2"
            >
              {imagePreviewUrl ? (
                <div className="relative inline-block max-w-full">
                  <img 
                    src={imagePreviewUrl} 
                    alt="Scan preview" 
                    className="max-h-[520px] w-auto object-contain rounded-lg shadow-md block"
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

                    const colorClass = conf >= 0.85 
                      ? 'border-emerald-500/70 hover:border-emerald-400 bg-emerald-500/10 hover:bg-emerald-500/30'
                      : conf >= 0.70
                      ? 'border-amber-500/70 hover:border-amber-400 bg-amber-500/10 hover:bg-amber-500/30'
                      : 'border-red-500/70 hover:border-red-400 bg-red-500/20 hover:bg-red-500/40';

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
                        }}
                        className={`absolute border transition-all cursor-pointer rounded-[2px] ${colorClass} ${
                          isHovered ? 'ring-2 ring-indigo-400 z-30 scale-105' : 'z-10'
                        }`}
                        title={`${box.word} (${(conf * 100).toFixed(0)}%)`}
                      />
                    );
                  })}
                </div>
              ) : (
                /* PDF Visual representation */
                <div className="w-full h-full min-h-[460px] p-6 bg-slate-950 text-slate-300 font-mono text-xs flex flex-col justify-between">
                  <div className="p-4 bg-slate-900/80 rounded-xl border border-slate-800 space-y-2">
                    <div className="flex items-center gap-2 text-indigo-400 font-semibold">
                      <FileText className="w-4 h-4" />
                      <span>Dual-Stream Digital PDF Extraction Active</span>
                    </div>
                    <p className="text-slate-400 leading-relaxed text-[11px]">
                      Extracted via pdfplumber character layer with visual Bengali normalization.
                      Tokens extracted: <strong className="text-slate-200">{bboxes.length} words</strong>.
                    </p>
                  </div>
                  <div className="text-center text-slate-500 text-xs py-12">
                    To inspect pixel-accurate visual bounding box overlays, upload a scanned document image (PNG, JPG, TIFF).
                  </div>
                  <div className="text-right text-[11px] text-slate-600">
                    Engine: {currentPage.engine || 'native'} ({currentPage.engine_version})
                  </div>
                </div>
              )}

              {/* Floating Tooltip when hovering a box */}
              {hoveredBox && (
                <div className="absolute bottom-4 left-4 right-4 bg-slate-950/90 backdrop-blur-md border border-slate-700/80 p-3 rounded-xl shadow-2xl flex items-center justify-between text-xs z-40 animate-in fade-in duration-150">
                  <div className="flex items-center gap-3">
                    <span className="font-bold text-white text-sm bg-slate-800 px-2.5 py-1 rounded-lg border border-slate-700">
                      &quot;{hoveredBox.word}&quot;
                    </span>
                    <div className="space-y-0.5">
                      <div className="text-slate-400 text-[11px]">
                        Normalized: <span className="font-mono text-indigo-300">[{hoveredBox.normalized_box?.join(', ')}]</span>
                      </div>
                      <div className="text-slate-400 text-[11px]">
                        Pixel size: <span className="font-mono text-slate-200">{hoveredBox.w} × {hoveredBox.h} px</span>
                      </div>
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="text-[11px] text-slate-400">Confidence:</span>
                    <span className={`font-bold font-mono px-2 py-0.5 rounded text-xs ${
                      (hoveredBox.confidence || 0) >= 0.85 ? 'bg-emerald-500/20 text-emerald-300' : 'bg-amber-500/20 text-amber-300'
                    }`}>
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
            <div className="bg-slate-900 border border-slate-800 rounded-2xl p-4 shadow-xl">
              <div className="grid grid-cols-3 gap-2 text-center">
                <div className="bg-slate-950/60 p-2.5 rounded-xl border border-slate-800/80">
                  <div className="text-[11px] text-slate-400">Total Words</div>
                  <div className="text-base font-bold text-white">{currentPage.words_count || ocrResult.total_words}</div>
                </div>
                <div className="bg-slate-950/60 p-2.5 rounded-xl border border-slate-800/80">
                  <div className="text-[11px] text-slate-400">Confidence</div>
                  <div className="text-base font-bold text-indigo-400">{(currentPage.confidence * 100).toFixed(1)}%</div>
                </div>
                <div className="bg-slate-950/60 p-2.5 rounded-xl border border-slate-800/80">
                  <div className="text-[11px] text-slate-400">Status</div>
                  <div className="text-xs font-semibold mt-1">
                    {currentPage.confidence >= 0.70 ? (
                      <span className="text-emerald-400 flex items-center justify-center gap-1">
                        <CheckCircle2 className="w-3.5 h-3.5" /> High Trust
                      </span>
                    ) : (
                      <span className="text-amber-400 flex items-center justify-center gap-1">
                        <AlertTriangle className="w-3.5 h-3.5" /> Needs Review
                      </span>
                    )}
                  </div>
                </div>
              </div>
            </div>

            {/* Extracted Text Box */}
            <div className="bg-slate-900 border border-slate-800 rounded-2xl p-4 flex-1 flex flex-col shadow-xl min-h-[300px]">
              <div className="flex items-center justify-between pb-3 border-b border-slate-800 mb-3">
                <div className="flex items-center gap-2">
                  <button 
                    onClick={() => setViewMode('text')}
                    className={`text-xs font-semibold px-2.5 py-1 rounded-lg transition-all ${
                      viewMode === 'text' ? 'bg-indigo-600 text-white' : 'text-slate-400 hover:text-white'
                    }`}
                  >
                    Repaired Text
                  </button>
                  <button 
                    onClick={() => setViewMode('tokens')}
                    className={`text-xs font-semibold px-2.5 py-1 rounded-lg transition-all ${
                      viewMode === 'tokens' ? 'bg-indigo-600 text-white' : 'text-slate-400 hover:text-white'
                    }`}
                  >
                    Token Badges ({bboxes.length})
                  </button>
                </div>

                <div className="flex items-center gap-1">
                  <button
                    onClick={() => navigator.clipboard.writeText(currentPage.text)}
                    className="p-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 hover:text-white transition-all text-xs flex items-center gap-1"
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
                    className="p-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 hover:text-white transition-all text-xs flex items-center gap-1"
                    title="Export JSON"
                  >
                    <Download className="w-3.5 h-3.5" />
                    <span>JSON</span>
                  </button>
                </div>
              </div>

              {viewMode === 'text' ? (
                <div className="flex-1 bg-slate-950/70 p-3.5 rounded-xl border border-slate-800 font-mono text-xs text-slate-200 overflow-y-auto whitespace-pre-wrap leading-relaxed select-text max-h-[320px]">
                  {currentPage.text || <span className="text-slate-600 italic">No text recognized</span>}
                </div>
              ) : (
                <div className="flex-1 bg-slate-950/70 p-3.5 rounded-xl border border-slate-800 overflow-y-auto max-h-[320px] flex flex-wrap gap-1.5 content-start">
                  {bboxes.map((b, i) => (
                    <span
                      key={i}
                      onMouseEnter={() => setHoveredBox(b)}
                      onMouseLeave={() => setHoveredBox(null)}
                      className={`text-xs px-2 py-0.5 rounded cursor-pointer transition-all border ${
                        (b.confidence || 0) >= 0.85
                          ? 'bg-emerald-950/40 text-emerald-300 border-emerald-800/60 hover:bg-emerald-800/40'
                          : (b.confidence || 0) >= 0.70
                          ? 'bg-amber-950/40 text-amber-300 border-amber-800/60 hover:bg-amber-800/40'
                          : 'bg-red-950/40 text-red-300 border-red-800/60 hover:bg-red-800/40'
                      }`}
                    >
                      {b.word}
                    </span>
                  ))}
                </div>
              )}
            </div>

            {/* Save to Knowledge Workspace Panel */}
            {workspaceId && (
              <div className="bg-gradient-to-b from-slate-900 to-slate-950 border border-slate-800 rounded-2xl p-4 shadow-xl">
                <div className="flex items-center gap-2 mb-3">
                  <Database className="w-4 h-4 text-indigo-400" />
                  <span className="text-xs font-bold text-white uppercase tracking-wider">
                    Index Directly Into Governed Workspace
                  </span>
                </div>

                <div className="space-y-3">
                  <div>
                    <label className="text-[11px] text-slate-400 block mb-1">Document Title</label>
                    <input 
                      type="text" 
                      value={docTitle}
                      onChange={(e) => setDocTitle(e.target.value)}
                      className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-1.5 text-xs text-white focus:outline-none focus:border-indigo-500"
                    />
                  </div>

                  <div className="grid grid-cols-2 gap-2">
                    <div>
                      <label className="text-[11px] text-slate-400 block mb-1">Authority Level</label>
                      <select
                        value={authorityLevel}
                        onChange={(e) => setAuthorityLevel(Number(e.target.value))}
                        className="w-full bg-slate-950 border border-slate-800 rounded-lg px-2 py-1.5 text-xs text-white focus:outline-none focus:border-indigo-500"
                      >
                        <option value={1}>Level 1: Working Draft / Slack</option>
                        <option value={2}>Level 2: Team Wiki</option>
                        <option value={3}>Level 3: Operational Procedure</option>
                        <option value={4}>Level 4: Statutory Policy / Deed</option>
                        <option value={5}>Level 5: Constitutional Law</option>
                      </select>
                    </div>

                    <div>
                      <label className="text-[11px] text-slate-400 block mb-1">Collection</label>
                      <select
                        value={targetCollectionId}
                        onChange={(e) => setTargetCollectionId(e.target.value)}
                        className="w-full bg-slate-950 border border-slate-800 rounded-lg px-2 py-1.5 text-xs text-white focus:outline-none focus:border-indigo-500"
                      >
                        <option value="">(Default Collection)</option>
                        {collections.map(c => (
                          <option key={c.id} value={c.id}>{c.name}</option>
                        ))}
                      </select>
                    </div>
                  </div>

                  {savedSuccessDocId ? (
                    <div className="p-3 bg-emerald-950/40 border border-emerald-800/60 rounded-xl flex items-center justify-between">
                      <div className="flex items-center gap-2 text-xs text-emerald-300 font-medium">
                        <CheckCircle2 className="w-4 h-4 text-emerald-400" />
                        <span>Indexed into Qdrant & Ready for RAG!</span>
                      </div>
                      {onNavigateToRAG && (
                        <button
                          onClick={onNavigateToRAG}
                          className="px-2.5 py-1 rounded bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-semibold flex items-center gap-1 transition-all"
                        >
                          <span>Query RAG</span>
                          <ArrowRight className="w-3.5 h-3.5" />
                        </button>
                      )}
                    </div>
                  ) : (
                    <button
                      onClick={handleSaveToWorkspace}
                      disabled={isSaving}
                      className="w-full py-2.5 rounded-xl bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white font-semibold text-xs transition-all shadow-lg shadow-indigo-600/20 flex items-center justify-center gap-2 active:scale-98"
                    >
                      {isSaving ? (
                        <>
                          <RefreshCw className="w-3.5 h-3.5 animate-spin" />
                          <span>Chunking, Embedding & Indexing Vectors...</span>
                        </>
                      ) : (
                        <>
                          <Sparkles className="w-3.5 h-3.5" />
                          <span>Save & Index to Knowledge Workspace</span>
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
        <div className="bg-slate-900/40 border border-slate-800/80 rounded-2xl p-12 text-center flex flex-col items-center justify-center gap-3">
          <div className="w-16 h-16 rounded-2xl bg-indigo-500/10 text-indigo-400 border border-indigo-500/20 flex items-center justify-center">
            <Scan className="w-8 h-8" />
          </div>
          <div className="text-base font-bold text-white">No Document Loaded Yet</div>
          <p className="text-xs text-slate-400 max-w-md">
            Click one of the quick test buttons above or drop a document image or PDF to experience real-time token extraction and phonetic repair.
          </p>
        </div>
      )}
    </div>
  );
};
