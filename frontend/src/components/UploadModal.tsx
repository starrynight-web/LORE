'use client';

import React, { useState, useRef, useEffect } from 'react';
import { 
  X, 
  Upload, 
  FileText, 
  AlertCircle, 
  Shield, 
  Hash, 
  ArrowRight, 
  CheckCircle2, 
  Trash2, 
  Plus, 
  FileSpreadsheet, 
  FileImage, 
  Presentation, 
  Code, 
  Check, 
  RefreshCw 
} from 'lucide-react';
import { Collection, api } from '@/lib/api';
import { useI18n } from '@/lib/i18n';

interface UploadFileItem {
  id: string;
  file: File;
  title: string;
  sha256?: string;
  sizeBytes: number;
  format: string;
  status: 'pending' | 'uploading' | 'completed' | 'failed';
  error?: string;
  docId?: string;
  jobId?: string;
}

interface UploadModalProps {
  isOpen: boolean;
  onClose: () => void;
  workspaceId: string;
  collections: Collection[];
  onUploadSuccess: (docId: string, jobId: string) => void;
}

export const UploadModal: React.FC<UploadModalProps> = ({
  isOpen,
  onClose,
  workspaceId,
  collections,
  onUploadSuccess
}) => {
  const { t } = useI18n();
  const [fileList, setFileList] = useState<UploadFileItem[]>([]);
  const [description, setDescription] = useState('');
  const [collectionId, setCollectionId] = useState('');
  const [authorityLevel, setAuthorityLevel] = useState(3);
  const [isUploading, setIsUploading] = useState(false);
  const [overallError, setOverallError] = useState<string | null>(null);
  const [uploadSummary, setUploadSummary] = useState<{ success: number; failed: number } | null>(null);

  const fileInputRef = useRef<HTMLInputElement>(null);

  // Reset state when modal is opened
  useEffect(() => {
    if (isOpen) {
      setFileList([]);
      setDescription('');
      setOverallError(null);
      setUploadSummary(null);
      setIsUploading(false);
    }
  }, [isOpen]);

  if (!isOpen) return null;

  const computeSHA256 = async (selectedFile: File): Promise<string> => {
    try {
      const buffer = await selectedFile.arrayBuffer();
      const hashBuffer = await window.crypto.subtle.digest('SHA-256', buffer);
      const hashArray = Array.from(new Uint8Array(hashBuffer));
      return hashArray.map(b => b.toString(16).padStart(2, '0')).join('');
    } catch (err) {
      console.warn("SHA-256 computation warning:", err);
      return '';
    }
  };

  const getFormatBadge = (filename: string) => {
    const ext = filename.split('.').pop()?.toLowerCase() || '';
    if (ext === 'pdf') {
      return { label: 'PDF', color: 'text-rose-500 bg-rose-500/10 border-rose-500/20', icon: FileText };
    }
    if (['docx', 'doc'].includes(ext)) {
      return { label: 'DOCX', color: 'text-blue-500 bg-blue-500/10 border-blue-500/20', icon: FileText };
    }
    if (['xlsx', 'xls'].includes(ext)) {
      return { label: 'XLSX', color: 'text-emerald-500 bg-emerald-500/10 border-emerald-500/20', icon: FileSpreadsheet };
    }
    if (ext === 'csv') {
      return { label: 'CSV', color: 'text-teal-500 bg-teal-500/10 border-teal-500/20', icon: FileSpreadsheet };
    }
    if (['png', 'jpg', 'jpeg', 'tiff', 'tif', 'webp'].includes(ext)) {
      return { label: ext.toUpperCase(), color: 'text-purple-500 bg-purple-500/10 border-purple-500/20', icon: FileImage };
    }
    if (['pptx', 'ppt'].includes(ext)) {
      return { label: 'PPTX', color: 'text-orange-500 bg-orange-500/10 border-orange-500/20', icon: Presentation };
    }
    if (['html', 'htm'].includes(ext)) {
      return { label: 'HTML', color: 'text-cyan-500 bg-cyan-500/10 border-cyan-500/20', icon: Code };
    }
    if (['md', 'markdown'].includes(ext)) {
      return { label: 'MD', color: 'text-amber-500 bg-amber-500/10 border-amber-500/20', icon: FileText };
    }
    return { label: ext.toUpperCase() || 'TXT', color: 'text-slate-500 bg-slate-500/10 border-slate-500/20', icon: FileText };
  };

  const addFiles = async (filesToAdd: File[]) => {
    if (!filesToAdd.length) return;
    setOverallError(null);
    setUploadSummary(null);

    const newItems: UploadFileItem[] = [];

    for (const f of filesToAdd) {
      // Avoid duplicate additions in the same upload batch
      const alreadyInList = fileList.some(item => item.file.name === f.name && item.file.size === f.size);
      if (alreadyInList) continue;

      const itemId = `${f.name}-${Date.now()}-${Math.random().toString(36).substring(2, 7)}`;
      const cleanTitle = f.name.replace(/\.[^/.]+$/, "");
      
      const item: UploadFileItem = {
        id: itemId,
        file: f,
        title: cleanTitle,
        sizeBytes: f.size,
        format: f.name.split('.').pop()?.toLowerCase() || 'unknown',
        status: 'pending'
      };

      newItems.push(item);
    }

    if (newItems.length === 0) return;

    setFileList(prev => [...prev, ...newItems]);

    // Asynchronously compute SHA-256 for provenance & deduplication checking
    for (const item of newItems) {
      computeSHA256(item.file).then(hashHex => {
        setFileList(prev => prev.map(f => f.id === item.id ? { ...f, sha256: hashHex } : f));
      });
    }
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files) {
      addFiles(Array.from(e.target.files));
      // Reset input value so same files can be re-selected if removed
      e.target.value = '';
    }
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    if (e.dataTransfer.files) {
      addFiles(Array.from(e.dataTransfer.files));
    }
  };

  const handleRemoveFile = (id: string) => {
    if (isUploading) return;
    setFileList(prev => prev.filter(item => item.id !== id));
  };

  const handleTitleChange = (id: string, newTitle: string) => {
    setFileList(prev => prev.map(item => item.id === id ? { ...item, title: newTitle } : item));
  };

  const handleClearAll = () => {
    if (isUploading) return;
    setFileList([]);
    setOverallError(null);
    setUploadSummary(null);
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!fileList.length) {
      setOverallError('Please select at least one document to upload.');
      return;
    }

    setIsUploading(true);
    setOverallError(null);
    setUploadSummary(null);

    // Mark all pending files as uploading
    setFileList(prev => prev.map(f => ({ ...f, status: 'uploading', error: undefined })));

    try {
      const formData = new FormData();
      fileList.forEach(item => {
        formData.append('files', item.file);
      });

      formData.append('workspace', workspaceId);
      formData.append('description', description);
      formData.append('authority_level', authorityLevel.toString());
      if (collectionId) {
        formData.append('collection', collectionId);
      }

      // Pass map of individual titles to prevent cross-document title conflation and RAG hallucination
      const titlesMap: Record<string, string> = {};
      fileList.forEach(item => {
        titlesMap[item.file.name] = item.title.trim() || item.file.name;
      });
      formData.append('titles', JSON.stringify(titlesMap));

      // Call bulk upload endpoint with partial-failure resilience
      const res = await api.bulkUploadDocuments(formData);

      let successCount = 0;
      let failedCount = 0;
      let firstDocId = '';
      let firstJobId = '';

      const successfulMap = new Map<string, { docId: string; jobId: string }>();
      if (res.successful) {
        res.successful.forEach(item => {
          successfulMap.set(item.document.original_filename, {
            docId: item.document.id,
            jobId: item.job_id
          });
          if (!firstDocId) {
            firstDocId = item.document.id;
            firstJobId = item.job_id;
          }
          successCount++;
        });
      }

      const failedMap = new Map<string, string>();
      if (res.failed) {
        res.failed.forEach(item => {
          failedMap.set(item.filename, item.error);
          failedCount++;
        });
      }

      setFileList(prev => prev.map(item => {
        if (successfulMap.has(item.file.name)) {
          const s = successfulMap.get(item.file.name)!;
          return { ...item, status: 'completed', docId: s.docId, jobId: s.jobId };
        } else if (failedMap.has(item.file.name)) {
          return { ...item, status: 'failed', error: failedMap.get(item.file.name) };
        } else {
          return { ...item, status: 'completed' };
        }
      }));

      setUploadSummary({ success: successCount, failed: failedCount });

      if (successCount > 0) {
        onUploadSuccess(firstDocId, firstJobId);
      }

      if (failedCount > 0 && successCount === 0) {
        setOverallError('All files failed to upload. Check file formats or quota.');
      }
    } catch (err: any) {
      setOverallError(err.message || 'Failed to upload documents.');
      setFileList(prev => prev.map(f => ({ ...f, status: 'failed', error: err.message || 'Upload failed' })));
    } finally {
      setIsUploading(false);
    }
  };

  const totalSizeMB = (fileList.reduce((acc, curr) => acc + curr.sizeBytes, 0) / (1024 * 1024)).toFixed(2);
  const isAllCompleted = fileList.length > 0 && fileList.every(f => f.status === 'completed');

  const authorityLadder = [
    { rank: 7, label: 'Approved Policy (Rank 7)', desc: 'Formally signed, approved security/governance policies.' },
    { rank: 6, label: 'Signed Contract (Rank 6)', desc: 'Executed vendor agreements, terms & legal obligations.' },
    { rank: 5, label: 'Team Convention (Rank 5)', desc: 'Official team standards and engineering conventions.' },
    { rank: 4, label: 'Maintained Procedure (Rank 4)', desc: 'Current runbooks, SOPs and technical guides.' },
    { rank: 3, label: 'Reviewed Document (Rank 3)', desc: 'Formally reviewed internal documentation.' },
    { rank: 2, label: 'Wiki Entry (Rank 2)', desc: 'Internal engineering wiki (provisional, condition-governed).' },
    { rank: 1, label: 'Informal Note (Rank 1)', desc: 'Meeting minutes, procurement notes, Slack updates.' },
  ];

  return (
    <div 
      className="fixed inset-0 z-50 flex items-center justify-center p-3 sm:p-4 backdrop-blur-sm"
      style={{ backgroundColor: 'var(--modal-overlay)' }}
    >
      <div 
        className="w-full max-w-2xl rounded-2xl border shadow-2xl overflow-hidden flex flex-col max-h-[92vh] animate-in fade-in zoom-in-95 duration-150"
        style={{
          backgroundColor: 'var(--bg-surface)',
          borderColor: 'var(--border-color)',
        }}
      >
        {/* Modal Header */}
        <div 
          className="flex items-center justify-between px-5 sm:px-6 py-4 border-b flex-shrink-0"
          style={{ borderColor: 'var(--border-color)' }}
        >
          <div className="flex items-center gap-3">
            <div 
              className="w-9 h-9 rounded-xl flex items-center justify-center border shadow-xs"
              style={{
                backgroundColor: 'var(--accent-light)',
                borderColor: 'var(--border-color)',
                color: 'var(--brand-accent)',
              }}
            >
              <Upload className="w-4 h-4" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h3 className="text-sm sm:text-base font-bold text-[var(--text-primary)]">
                  {t('upload.modal_title')}
                </h3>
                {fileList.length > 0 && (
                  <span 
                    className="text-[11px] font-semibold px-2 py-0.5 rounded-full border"
                    style={{
                      backgroundColor: 'var(--bg-surface-soft)',
                      borderColor: 'var(--border-color)',
                      color: 'var(--brand-accent)'
                    }}
                  >
                    {fileList.length} {t('upload.files_selected')} ({totalSizeMB} MB)
                  </span>
                )}
              </div>
              <p className="text-xs text-[var(--text-muted)] line-clamp-1 mt-0.5">
                {t('upload.supported_formats')}
              </p>
            </div>
          </div>
          <button 
            onClick={onClose}
            disabled={isUploading}
            className="p-1.5 rounded-xl border transition cursor-pointer hover:border-[var(--brand-accent)] disabled:opacity-50"
            style={{
              backgroundColor: 'var(--bg-surface-soft)',
              borderColor: 'var(--border-color)',
              color: 'var(--text-muted)',
            }}
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Form Body */}
        <form onSubmit={handleSubmit} className="p-5 sm:p-6 space-y-4 overflow-y-auto flex-1">
          {overallError && (
            <div 
              className="p-3 rounded-xl border text-xs flex items-center gap-2 animate-in fade-in"
              style={{
                backgroundColor: 'var(--error-bg)',
                borderColor: 'var(--border-color)',
                color: 'var(--error)',
              }}
            >
              <AlertCircle className="w-4 h-4 flex-shrink-0" />
              <span>{overallError}</span>
            </div>
          )}

          {uploadSummary && (
            <div 
              className="p-3.5 rounded-xl border text-xs flex items-center justify-between animate-in fade-in"
              style={{
                backgroundColor: uploadSummary.failed === 0 ? 'var(--success-bg)' : 'var(--bg-surface-soft)',
                borderColor: uploadSummary.failed === 0 ? 'var(--success)' : 'var(--border-color)',
                color: uploadSummary.failed === 0 ? 'var(--success)' : 'var(--text-primary)',
              }}
            >
              <div className="flex items-center gap-2">
                <CheckCircle2 className="w-4 h-4 flex-shrink-0 text-[var(--success)]" />
                <span>
                  {uploadSummary.success} document{uploadSummary.success > 1 ? 's' : ''} successfully ingested into the knowledge grid.
                  {uploadSummary.failed > 0 && ` (${uploadSummary.failed} failed)`}
                </span>
              </div>
              <span className="text-[11px] font-mono opacity-80">6-Stage Settlement Passed</span>
            </div>
          )}

          {/* Hidden multi-file input */}
          <input
            ref={fileInputRef}
            type="file"
            multiple
            onChange={handleFileChange}
            className="hidden"
            accept=".pdf,.docx,.txt,.md,.markdown,.csv,.xlsx,.xls,.png,.jpg,.jpeg,.tiff,.tif,.webp,.pptx,.ppt,.html,.htm"
          />

          {/* Drag & Drop Zone */}
          <div
            onDragOver={(e) => e.preventDefault()}
            onDrop={handleDrop}
            onClick={() => !isUploading && fileInputRef.current?.click()}
            className={`border-2 border-dashed rounded-2xl p-5 text-center cursor-pointer transition-all duration-200 ${
              isUploading ? 'opacity-50 cursor-not-allowed' : 'hover:border-[var(--brand-accent)]'
            }`}
            style={{
              backgroundColor: 'var(--bg-surface-soft)',
              borderColor: 'var(--border-color)',
            }}
          >
            <div className="flex flex-col items-center">
              <div 
                className="w-12 h-12 rounded-2xl flex items-center justify-center mb-2.5 border"
                style={{
                  backgroundColor: 'var(--accent-light)',
                  borderColor: 'var(--border-color)',
                  color: 'var(--brand-accent)',
                }}
              >
                <Upload className="w-6 h-6" />
              </div>
              <span className="text-xs sm:text-sm font-bold text-[var(--text-primary)]">
                {t('upload.drag_drop')}
              </span>
              <span className="text-[11px] sm:text-xs text-[var(--text-muted)] mt-0.5">
                {t('upload.or_browse')}
              </span>

              {/* Supported format badges */}
              <div className="flex flex-wrap items-center justify-center gap-1.5 mt-3 pt-3 border-t border-[var(--border-color)]/60 max-w-md">
                {['PDF', 'DOCX', 'XLSX', 'CSV', 'PPTX', 'PNG / JPG', 'TIFF', 'HTML', 'Markdown'].map(fmt => (
                  <span 
                    key={fmt} 
                    className="text-[10px] font-medium px-2 py-0.5 rounded-md border"
                    style={{
                      backgroundColor: 'var(--bg-surface)',
                      borderColor: 'var(--border-color)',
                      color: 'var(--text-secondary)'
                    }}
                  >
                    {fmt}
                  </span>
                ))}
              </div>
            </div>
          </div>

          {/* Queued Files List with Anti-Hallucination Titles */}
          {fileList.length > 0 && (
            <div className="space-y-2">
              <div className="flex items-center justify-between text-xs font-semibold text-[var(--text-secondary)]">
                <span className="flex items-center gap-1.5">
                  <Shield className="w-3.5 h-3.5 text-[var(--brand-accent)]" />
                  <span>{t('upload.individual_titles')}</span>
                </span>
                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    onClick={() => fileInputRef.current?.click()}
                    disabled={isUploading}
                    className="text-[11px] font-medium text-[var(--brand-accent)] hover:underline flex items-center gap-1 cursor-pointer disabled:opacity-50"
                  >
                    <Plus className="w-3 h-3" />
                    <span>{t('upload.add_more')}</span>
                  </button>
                  <span className="text-[var(--border-color)]">•</span>
                  <button
                    type="button"
                    onClick={handleClearAll}
                    disabled={isUploading}
                    className="text-[11px] font-medium text-[var(--text-muted)] hover:text-red-500 cursor-pointer disabled:opacity-50"
                  >
                    {t('upload.clear_all')}
                  </button>
                </div>
              </div>

              <div 
                className="max-h-56 overflow-y-auto space-y-2 pr-1 rounded-xl"
              >
                {fileList.map((item, idx) => {
                  const badge = getFormatBadge(item.file.name);
                  const BadgeIcon = badge.icon;
                  const sizeMB = (item.sizeBytes / (1024 * 1024)).toFixed(2);

                  return (
                    <div 
                      key={item.id}
                      className="p-3 rounded-xl border transition-all duration-150 flex flex-col sm:flex-row sm:items-center justify-between gap-2.5"
                      style={{
                        backgroundColor: item.status === 'completed' ? 'var(--accent-light)' : 'var(--bg-surface-soft)',
                        borderColor: item.status === 'failed' ? 'var(--error)' : 'var(--border-color)',
                      }}
                    >
                      {/* Left: format badge + editable title & details */}
                      <div className="flex items-start gap-2.5 flex-1 min-w-0">
                        <div className={`px-2 py-1 rounded-lg border text-[11px] font-bold flex items-center gap-1 flex-shrink-0 ${badge.color}`}>
                          <BadgeIcon className="w-3.5 h-3.5" />
                          <span>{badge.label}</span>
                        </div>

                        <div className="flex-1 min-w-0">
                          {/* Individual title input for contextual grounding */}
                          <input
                            type="text"
                            value={item.title}
                            disabled={isUploading || item.status === 'completed'}
                            onChange={(e) => handleTitleChange(item.id, e.target.value)}
                            placeholder="Enter distinct document title..."
                            className="w-full text-xs font-semibold px-2 py-1 rounded-lg border focus:outline-none transition-colors"
                            style={{
                              backgroundColor: 'var(--input-bg)',
                              borderColor: 'var(--input-border)',
                              color: 'var(--text-primary)',
                            }}
                          />
                          <div className="flex items-center gap-2 mt-1 text-[11px] text-[var(--text-muted)]">
                            <span className="truncate max-w-[180px] sm:max-w-[240px]" title={item.file.name}>
                              {item.file.name}
                            </span>
                            <span>•</span>
                            <span>{sizeMB} MB</span>
                            {item.sha256 && (
                              <>
                                <span>•</span>
                                <span className="font-mono text-[10px] truncate max-w-[100px]" title={`SHA-256: ${item.sha256}`}>
                                  {item.sha256.substring(0, 8)}...
                                </span>
                              </>
                            )}
                          </div>

                          {item.error && (
                            <div className="text-[11px] text-[var(--error)] mt-1 flex items-center gap-1">
                              <AlertCircle className="w-3 h-3 flex-shrink-0" />
                              <span>{item.error}</span>
                            </div>
                          )}
                        </div>
                      </div>

                      {/* Right: status indicator & delete button */}
                      <div className="flex items-center gap-2 self-end sm:self-center flex-shrink-0">
                        {item.status === 'pending' && (
                          <span 
                            className="text-[11px] font-medium px-2 py-0.5 rounded-md border text-[var(--text-muted)]"
                            style={{ borderColor: 'var(--border-color)', backgroundColor: 'var(--bg-surface)' }}
                          >
                            {t('upload.ready_badge')}
                          </span>
                        )}
                        {item.status === 'uploading' && (
                          <span className="flex items-center gap-1 text-[11px] font-semibold text-[var(--brand-accent)]">
                            <RefreshCw className="w-3 h-3 animate-spin" />
                            <span>{t('upload.ingesting_badge')}</span>
                          </span>
                        )}
                        {item.status === 'completed' && (
                          <span className="flex items-center gap-1 text-[11px] font-semibold text-[var(--success)]">
                            <Check className="w-3.5 h-3.5" />
                            <span>{t('upload.indexed_badge')}</span>
                          </span>
                        )}
                        {item.status === 'failed' && (
                          <span className="flex items-center gap-1 text-[11px] font-semibold text-[var(--error)]">
                            <AlertCircle className="w-3.5 h-3.5" />
                            <span>{t('upload.error_badge')}</span>
                          </span>
                        )}

                        {!isUploading && item.status !== 'completed' && (
                          <button
                            type="button"
                            onClick={() => handleRemoveFile(item.id)}
                            className="p-1 rounded-lg border text-[var(--text-muted)] hover:text-red-500 hover:border-red-500/30 transition cursor-pointer"
                            style={{ borderColor: 'var(--border-color)' }}
                            title="Remove from queue"
                          >
                            <Trash2 className="w-3.5 h-3.5" />
                          </button>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* Collection & Authority Ladder */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 pt-1">
            <div>
              <label className="block text-xs font-semibold text-[var(--text-secondary)] mb-1">
                {t('upload.collection_label')}
              </label>
              <select
                value={collectionId}
                disabled={isUploading}
                onChange={(e) => setCollectionId(e.target.value)}
                className="w-full border rounded-xl px-3 py-2 text-xs sm:text-sm focus:outline-none cursor-pointer disabled:opacity-50"
                style={{
                  backgroundColor: 'var(--input-bg)',
                  borderColor: 'var(--input-border)',
                  color: 'var(--text-primary)',
                }}
              >
                <option value="">{t('upload.default_collection')}</option>
                {collections.map(c => (
                  <option key={c.id} value={c.id}>{c.name}</option>
                ))}
              </select>
            </div>

            <div>
              <label className="block text-xs font-semibold text-[var(--text-secondary)] mb-1 flex items-center justify-between">
                <span>Authority Ladder (LORE L6)</span>
                <span className="text-[10px] text-[var(--text-muted)]">Precedence Rank</span>
              </label>
              <select
                value={authorityLevel}
                disabled={isUploading}
                onChange={(e) => setAuthorityLevel(Number(e.target.value))}
                className="w-full border rounded-xl px-3 py-2 text-xs sm:text-sm focus:outline-none cursor-pointer disabled:opacity-50"
                style={{
                  backgroundColor: 'var(--input-bg)',
                  borderColor: 'var(--input-border)',
                  color: 'var(--text-primary)',
                }}
              >
                {authorityLadder.map(item => (
                  <option key={item.rank} value={item.rank}>
                    {item.label}
                  </option>
                ))}
              </select>
            </div>
          </div>

          {/* Description (Optional) */}
          <div>
            <label className="block text-xs font-semibold text-[var(--text-secondary)] mb-1">
              Batch Ingestion Notes (Optional)
            </label>
            <input
              type="text"
              value={description}
              disabled={isUploading}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="e.g. Q3 Audited Financial Statements, HR Onboarding Guidelines..."
              className="w-full border rounded-xl px-3 py-2 text-xs sm:text-sm focus:outline-none disabled:opacity-50"
              style={{
                backgroundColor: 'var(--input-bg)',
                borderColor: 'var(--input-border)',
                color: 'var(--text-primary)',
              }}
            />
          </div>

          {/* Action Buttons */}
          <div 
            className="pt-3 flex items-center justify-between border-t flex-shrink-0"
            style={{ borderColor: 'var(--border-color)' }}
          >
            <div className="text-[11px] text-[var(--text-muted)] flex items-center gap-1.5">
              <Shield className="w-3.5 h-3.5 text-[var(--brand-accent)]" />
              <span>Grounded in Six-Stage Settlement Gate</span>
            </div>

            <div className="flex items-center gap-2.5">
              <button
                type="button"
                onClick={onClose}
                disabled={isUploading}
                className="px-4 py-2 text-xs sm:text-sm font-semibold rounded-xl border transition cursor-pointer"
                style={{
                  backgroundColor: 'var(--bg-surface-soft)',
                  borderColor: 'var(--border-color)',
                  color: 'var(--text-secondary)',
                }}
              >
                {isAllCompleted ? 'Close' : t('common.cancel')}
              </button>

              {!isAllCompleted ? (
                <button
                  type="submit"
                  disabled={fileList.length === 0 || isUploading}
                  className="flex items-center gap-2 px-5 py-2 rounded-xl text-xs sm:text-sm font-semibold shadow-sm transition cursor-pointer active:scale-95 disabled:opacity-50"
                  style={{
                    backgroundColor: 'var(--brand-accent)',
                    color: 'var(--cta-text)',
                  }}
                >
                  {isUploading ? (
                    <>
                      <div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                      <span>{t('upload.processing_btn')}</span>
                    </>
                  ) : (
                    <>
                      <span>
                        {fileList.length > 1 
                          ? `${t('upload.ingest_all')} (${fileList.length})` 
                          : t('upload.start_btn')}
                      </span>
                      <ArrowRight className="w-4 h-4" />
                    </>
                  )}
                </button>
              ) : (
                <button
                  type="button"
                  onClick={onClose}
                  className="flex items-center gap-2 px-5 py-2 rounded-xl text-xs sm:text-sm font-semibold shadow-sm transition cursor-pointer active:scale-95"
                  style={{
                    backgroundColor: 'var(--brand-accent)',
                    color: 'var(--cta-text)',
                  }}
                >
                  <span>Done</span>
                  <Check className="w-4 h-4" />
                </button>
              )}
            </div>
          </div>
        </form>
      </div>
    </div>
  );
};
