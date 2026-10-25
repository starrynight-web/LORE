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
  RefreshCw,
  Archive,
  Download,
  AlertTriangle,
  Layers,
  Ban
} from 'lucide-react';
import { Collection, ZipImportJob, ZipImportEntry, api } from '@/lib/api';
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

  // ZIP Ingestion Engine State
  const [zipFile, setZipFile] = useState<File | null>(null);
  const [zipJob, setZipJob] = useState<ZipImportJob | null>(null);
  const [isZipPreviewing, setIsZipPreviewing] = useState<boolean>(false);
  const [isZipImporting, setIsZipImporting] = useState<boolean>(false);
  const [zipFilter, setZipFilter] = useState<'all' | 'supported' | 'unsupported'>('all');

  const fileInputRef = useRef<HTMLInputElement>(null);

  // Reset state when modal is opened or closed
  useEffect(() => {
    if (isOpen) {
      setFileList([]);
      setDescription('');
      setOverallError(null);
      setUploadSummary(null);
      setIsUploading(false);
      setZipFile(null);
      setZipJob(null);
      setIsZipPreviewing(false);
      setIsZipImporting(false);
      setZipFilter('all');
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
    if (ext === 'json') {
      return { label: 'JSON / Slack', color: 'text-emerald-500 bg-emerald-500/10 border-emerald-500/20', icon: Code };
    }
    if (['md', 'markdown'].includes(ext)) {
      return { label: 'MD', color: 'text-amber-500 bg-amber-500/10 border-amber-500/20', icon: FileText };
    }
    if (ext === 'zip') {
      return { label: 'ZIP', color: 'text-indigo-500 bg-indigo-500/10 border-indigo-500/20', icon: Archive };
    }
    return { label: ext.toUpperCase() || 'TXT', color: 'text-slate-500 bg-slate-500/10 border-slate-500/20', icon: FileText };
  };

  const handleZipPreview = async (file: File) => {
    setIsZipPreviewing(true);
    setOverallError(null);
    setZipFile(file);
    try {
      const formData = new FormData();
      formData.append('file', file);
      formData.append('workspace', workspaceId);
      if (collectionId) formData.append('collection', collectionId);
      formData.append('authority_level', authorityLevel.toString());
      formData.append('description', description);

      const job = await api.previewZipArchive(formData);
      setZipJob(job);
    } catch (err: any) {
      setOverallError(err.message || 'ZIP archive validation and security scan failed.');
      setZipFile(null);
      setZipJob(null);
    } finally {
      setIsZipPreviewing(false);
    }
  };

  const addFiles = async (filesToAdd: File[]) => {
    if (!filesToAdd.length) return;
    setOverallError(null);
    setUploadSummary(null);

    // If single ZIP archive selected, route to ZIP Engine Preview
    if (filesToAdd.length === 1 && filesToAdd[0].name.toLowerCase().endsWith('.zip')) {
      await handleZipPreview(filesToAdd[0]);
      return;
    }

    const newItems: UploadFileItem[] = [];

    for (const f of filesToAdd) {
      if (f.name.toLowerCase().endsWith('.zip')) {
        // If multiple files include a zip, alert user to upload zip archives individually
        setOverallError('ZIP archives should be uploaded individually to inspect and preview archive contents.');
        continue;
      }
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

    for (const item of newItems) {
      computeSHA256(item.file).then(hashHex => {
        setFileList(prev => prev.map(f => f.id === item.id ? { ...f, sha256: hashHex } : f));
      });
    }
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files) {
      addFiles(Array.from(e.target.files));
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
    if (isUploading || isZipImporting) return;
    setFileList([]);
    setZipFile(null);
    setZipJob(null);
    setOverallError(null);
    setUploadSummary(null);
  };

  // Regular multi-file upload submit
  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!fileList.length) {
      setOverallError('Please select at least one document to upload.');
      return;
    }

    setIsUploading(true);
    setOverallError(null);
    setUploadSummary(null);

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

      const titlesMap: Record<string, string> = {};
      fileList.forEach(item => {
        titlesMap[item.file.name] = item.title.trim() || item.file.name;
      });
      formData.append('titles', JSON.stringify(titlesMap));

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

  // ZIP Import Actions
  const handleStartZipImport = async () => {
    if (!zipJob) return;
    setIsZipImporting(true);
    setOverallError(null);
    try {
      const updatedJob = await api.startZipImport(zipJob.id);
      setZipJob(updatedJob);
      const firstImported = updatedJob.entries.find(e => e.status === 'imported' && e.document_id);
      if (firstImported && firstImported.document_id) {
        onUploadSuccess(firstImported.document_id, firstImported.ingestion_job_id || '');
      }
    } catch (err: any) {
      setOverallError(err.message || 'ZIP import processing failed.');
    } finally {
      setIsZipImporting(false);
    }
  };

  const handleCancelZipImport = async () => {
    if (!zipJob) return;
    try {
      const cancelledJob = await api.cancelZipImport(zipJob.id);
      setZipJob(cancelledJob);
    } catch (err: any) {
      setOverallError(err.message || 'Failed to cancel ZIP import.');
    }
  };

  const handleRetryZipFailed = async () => {
    if (!zipJob) return;
    setIsZipImporting(true);
    setOverallError(null);
    try {
      const retriedJob = await api.retryZipImport(zipJob.id);
      setZipJob(retriedJob);
      const firstImported = retriedJob.entries.find(e => e.status === 'imported' && e.document_id);
      if (firstImported && firstImported.document_id) {
        onUploadSuccess(firstImported.document_id, firstImported.ingestion_job_id || '');
      }
    } catch (err: any) {
      setOverallError(err.message || 'Failed to retry failed entries.');
    } finally {
      setIsZipImporting(false);
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

  const filteredZipEntries = zipJob?.entries.filter(e => {
    if (zipFilter === 'supported') return e.is_supported;
    if (zipFilter === 'unsupported') return !e.is_supported;
    return true;
  }) || [];

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
              {zipJob || zipFile ? <Archive className="w-4 h-4" /> : <Upload className="w-4 h-4" />}
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h3 className="text-sm sm:text-base font-bold text-[var(--text-primary)]">
                  {zipJob || zipFile ? 'ZIP Archive Ingestion Engine' : t('upload.modal_title')}
                </h3>
                {zipJob && (
                  <span 
                    className="text-[11px] font-semibold px-2 py-0.5 rounded-full border"
                    style={{
                      backgroundColor: 'var(--bg-surface-soft)',
                      borderColor: 'var(--border-color)',
                      color: 'var(--brand-accent)'
                    }}
                  >
                    {zipJob.supported_entries} Supported / {zipJob.total_entries} Files
                  </span>
                )}
                {!zipJob && fileList.length > 0 && (
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
                {zipJob || zipFile 
                  ? 'Deep security verified (Zip Slip, Bomb, & Encryption shielded)' 
                  : t('upload.supported_formats')}
              </p>
            </div>
          </div>
          <button 
            onClick={onClose}
            disabled={isUploading || isZipImporting}
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

        {/* ========================================================================= */}
        {/* VIEW 1: ZIP ARCHIVE INSPECTOR & IMPORT WORKBENCH */}
        {/* ========================================================================= */}
        {zipJob || isZipPreviewing ? (
          <div className="p-5 sm:p-6 space-y-4 overflow-y-auto flex-1">
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

            {isZipPreviewing ? (
              <div className="py-12 flex flex-col items-center justify-center text-center space-y-3">
                <div className="w-10 h-10 border-3 border-[var(--brand-accent)]/30 border-t-[var(--brand-accent)] rounded-full animate-spin" />
                <span className="text-sm font-bold text-[var(--text-primary)]">
                  Inspecting ZIP archive & running security pre-scan...
                </span>
                <span className="text-xs text-[var(--text-muted)] max-w-sm">
                  Checking for Zip Slip path traversals, decompression ratios, magic byte integrity, and nested archives.
                </span>
              </div>
            ) : zipJob && (
              <>
                {/* Archive Metadata Bar */}
                <div 
                  className="p-3.5 rounded-2xl border flex flex-col sm:flex-row sm:items-center justify-between gap-3"
                  style={{
                    backgroundColor: 'var(--bg-surface-soft)',
                    borderColor: 'var(--border-color)',
                  }}
                >
                  <div className="flex items-center gap-3">
                    <div 
                      className="w-10 h-10 rounded-xl border flex items-center justify-center flex-shrink-0"
                      style={{
                        backgroundColor: 'var(--accent-light)',
                        borderColor: 'var(--border-color)',
                        color: 'var(--brand-accent)'
                      }}
                    >
                      <Archive className="w-5 h-5" />
                    </div>
                    <div>
                      <div className="flex items-center gap-2">
                        <span className="font-bold text-sm block text-[var(--text-primary)]">
                          {zipJob.archive_filename}
                        </span>
                        {zipJob.is_slack_export && (
                          <span className="px-2 py-0.5 rounded-md text-[10px] font-bold bg-[#4A154B]/20 text-[#ECB22E] border border-[#E01E5A]/30">
                            Slack Workspace Export
                          </span>
                        )}
                      </div>
                      <span className="text-[11px] font-mono text-[var(--text-muted)]">
                        {(zipJob.archive_size / (1024 * 1024)).toFixed(2)} MB • SHA-256: {zipJob.archive_hash.substring(0, 16)}...
                      </span>
                    </div>
                  </div>

                  {/* Summary Status Badges */}
                  <div className="flex items-center gap-2 flex-wrap">
                    <span 
                      className="px-2.5 py-1 rounded-lg text-xs font-semibold border flex items-center gap-1"
                      style={{
                        backgroundColor: 'var(--success-bg)',
                        color: 'var(--success)',
                        borderColor: 'var(--border-color)'
                      }}
                    >
                      <CheckCircle2 className="w-3.5 h-3.5" />
                      <span>{zipJob.supported_entries} Supported</span>
                    </span>

                    {zipJob.unsupported_entries > 0 && (
                      <span 
                        className="px-2.5 py-1 rounded-lg text-xs font-semibold border flex items-center gap-1"
                        style={{
                          backgroundColor: 'var(--warning-bg)',
                          color: 'var(--warning)',
                          borderColor: 'var(--border-color)'
                        }}
                      >
                        <AlertTriangle className="w-3.5 h-3.5" />
                        <span>{zipJob.unsupported_entries} Skipped</span>
                      </span>
                    )}

                    <span 
                      className="px-2.5 py-1 rounded-lg text-xs font-mono font-semibold uppercase border"
                      style={{
                        backgroundColor: 'var(--bg-surface)',
                        color: 'var(--text-secondary)',
                        borderColor: 'var(--border-color)'
                      }}
                    >
                      {zipJob.status}
                    </span>
                  </div>
                </div>

                {/* Filter Tabs */}
                <div className="flex items-center gap-2 border-b pb-2" style={{ borderColor: 'var(--border-color)' }}>
                  <button
                    type="button"
                    onClick={() => setZipFilter('all')}
                    className={`px-3 py-1 rounded-lg text-xs font-semibold transition cursor-pointer ${
                      zipFilter === 'all' ? 'bg-[var(--accent-light)] text-[var(--brand-accent)]' : 'text-[var(--text-muted)] hover:text-[var(--text-primary)]'
                    }`}
                  >
                    All Entries ({zipJob.total_entries})
                  </button>
                  <button
                    type="button"
                    onClick={() => setZipFilter('supported')}
                    className={`px-3 py-1 rounded-lg text-xs font-semibold transition cursor-pointer ${
                      zipFilter === 'supported' ? 'bg-[var(--accent-light)] text-[var(--brand-accent)]' : 'text-[var(--text-muted)] hover:text-[var(--text-primary)]'
                    }`}
                  >
                    Supported ({zipJob.supported_entries})
                  </button>
                  <button
                    type="button"
                    onClick={() => setZipFilter('unsupported')}
                    className={`px-3 py-1 rounded-lg text-xs font-semibold transition cursor-pointer ${
                      zipFilter === 'unsupported' ? 'bg-[var(--accent-light)] text-[var(--brand-accent)]' : 'text-[var(--text-muted)] hover:text-[var(--text-primary)]'
                    }`}
                  >
                    Unsupported / Skipped ({zipJob.unsupported_entries})
                  </button>
                </div>

                {/* Entry List */}
                <div 
                  className="border rounded-2xl divide-y max-h-64 overflow-y-auto"
                  style={{
                    backgroundColor: 'var(--bg-surface)',
                    borderColor: 'var(--border-color)'
                  }}
                >
                  {filteredZipEntries.length === 0 ? (
                    <div className="p-6 text-center text-xs text-[var(--text-muted)]">
                      No files match the selected filter.
                    </div>
                  ) : (
                    filteredZipEntries.map(entry => {
                      const badge = getFormatBadge(entry.sanitized_filename);
                      const BadgeIcon = badge.icon;

                      return (
                        <div key={entry.id} className="p-3 flex items-center justify-between gap-3 text-xs">
                          <div className="flex items-center gap-2.5 min-w-0">
                            <span className={`px-2 py-0.5 rounded-md border text-[10px] font-bold flex items-center gap-1 ${badge.color}`}>
                              <BadgeIcon className="w-3 h-3" />
                              <span>{badge.label}</span>
                            </span>
                            <div className="min-w-0">
                              <div className="flex items-center gap-1.5">
                                <span className="font-semibold block truncate text-[var(--text-primary)]">
                                  {entry.entry_path}
                                </span>
                                {entry.is_private && (
                                  <span className="px-1.5 py-0.5 rounded text-[9px] font-semibold bg-rose-500/15 text-rose-400 border border-rose-500/30 flex items-center gap-0.5">
                                    <Shield className="w-2.5 h-2.5" />
                                    Private / Restricted
                                  </span>
                                )}
                              </div>
                              <span className="text-[11px] text-[var(--text-muted)]">
                                {(entry.file_size / 1024).toFixed(1)} KB
                                {entry.skip_reason && (
                                  <span className="text-[var(--warning)] ml-2">• {entry.skip_reason}</span>
                                )}
                                {entry.error_message && (
                                  <span className="text-[var(--error)] ml-2 font-semibold">• {entry.error_message}</span>
                                )}
                              </span>
                            </div>
                          </div>

                          {/* Status Badge */}
                          <div className="flex-shrink-0">
                            {entry.status === 'imported' && (
                              <span className="inline-flex items-center gap-1 text-[11px] font-semibold text-[var(--success)]">
                                <CheckCircle2 className="w-3.5 h-3.5" />
                                <span>Imported</span>
                              </span>
                            )}
                            {entry.status === 'failed' && (
                              <span className="inline-flex items-center gap-1 text-[11px] font-semibold text-[var(--error)]">
                                <AlertCircle className="w-3.5 h-3.5" />
                                <span>Failed</span>
                              </span>
                            )}
                            {entry.status === 'skipped' && (
                              <span className="inline-flex items-center gap-1 text-[11px] font-semibold text-[var(--text-muted)]">
                                <Ban className="w-3.5 h-3.5" />
                                <span>Skipped</span>
                              </span>
                            )}
                            {entry.status === 'cancelled' && (
                              <span className="text-[11px] text-[var(--text-muted)]">Cancelled</span>
                            )}
                            {entry.status === 'pending' && (
                              <span className="text-[11px] text-[var(--brand-accent)] font-medium">Ready</span>
                            )}
                          </div>
                        </div>
                      );
                    })
                  )}
                </div>

                {/* Governance Options */}
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 pt-2">
                  <div>
                    <label className="block text-xs font-semibold text-[var(--text-secondary)] mb-1">
                      {t('upload.collection_label')}
                    </label>
                    <select
                      value={collectionId}
                      disabled={isZipImporting || zipJob.status !== 'previewed'}
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
                      disabled={isZipImporting || zipJob.status !== 'previewed'}
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

                {/* Progress or Completion Bar */}
                {['completed', 'partial_success', 'failed'].includes(zipJob.status) && (
                  <div 
                    className="p-3.5 rounded-xl border text-xs flex items-center justify-between animate-in fade-in"
                    style={{
                      backgroundColor: zipJob.failed_count === 0 ? 'var(--success-bg)' : 'var(--bg-surface-soft)',
                      borderColor: zipJob.failed_count === 0 ? 'var(--success)' : 'var(--border-color)',
                      color: zipJob.failed_count === 0 ? 'var(--success)' : 'var(--text-primary)',
                    }}
                  >
                    <div className="flex items-center gap-2">
                      <CheckCircle2 className="w-4 h-4 flex-shrink-0 text-[var(--success)]" />
                      <span>
                        Import finished: <strong>{zipJob.success_count}</strong> imported, <strong>{zipJob.failed_count}</strong> failed, <strong>{zipJob.skipped_count}</strong> skipped.
                      </span>
                    </div>

                    <a
                      href={api.getZipImportSummaryCsvUrl(zipJob.id)}
                      download
                      className="flex items-center gap-1.5 px-3 py-1 rounded-lg border text-xs font-semibold transition hover:bg-[var(--bg-surface)] text-[var(--text-primary)] cursor-pointer"
                      style={{ borderColor: 'var(--border-color)' }}
                    >
                      <Download className="w-3.5 h-3.5 text-[var(--brand-accent)]" />
                      <span>Summary CSV</span>
                    </a>
                  </div>
                )}
              </>
            )}

            {/* ZIP Actions Footer */}
            <div 
              className="pt-3 flex items-center justify-between border-t flex-shrink-0"
              style={{ borderColor: 'var(--border-color)' }}
            >
              <div className="text-[11px] text-[var(--text-muted)] flex items-center gap-1.5">
                <Shield className="w-3.5 h-3.5 text-[var(--brand-accent)]" />
                <span>Zip Slip Traversal & Bomb Protected</span>
              </div>

              <div className="flex items-center gap-2.5">
                <button
                  type="button"
                  onClick={handleClearAll}
                  disabled={isZipImporting}
                  className="px-4 py-2 text-xs sm:text-sm font-semibold rounded-xl border transition cursor-pointer disabled:opacity-50"
                  style={{
                    backgroundColor: 'var(--bg-surface-soft)',
                    borderColor: 'var(--border-color)',
                    color: 'var(--text-secondary)',
                  }}
                >
                  Clear Archive
                </button>

                {zipJob?.status === 'previewed' && (
                  <button
                    type="button"
                    onClick={handleStartZipImport}
                    disabled={zipJob.supported_entries === 0 || isZipImporting}
                    className="flex items-center gap-2 px-5 py-2 rounded-xl text-xs sm:text-sm font-semibold shadow-sm transition cursor-pointer active:scale-95 disabled:opacity-50"
                    style={{
                      backgroundColor: 'var(--brand-accent)',
                      color: 'var(--cta-text)',
                    }}
                  >
                    {isZipImporting ? (
                      <>
                        <div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                        <span>Importing Archive...</span>
                      </>
                    ) : (
                      <>
                        <span>Start Import ({zipJob.supported_entries})</span>
                        <ArrowRight className="w-4 h-4" />
                      </>
                    )}
                  </button>
                )}

                {isZipImporting && (
                  <button
                    type="button"
                    onClick={handleCancelZipImport}
                    className="px-4 py-2 text-xs sm:text-sm font-semibold rounded-xl border transition text-[var(--error)] border-[var(--error)] cursor-pointer"
                  >
                    Cancel Import
                  </button>
                )}

                {zipJob && ['completed', 'partial_success', 'failed'].includes(zipJob.status) && (
                  <>
                    {zipJob.failed_count > 0 && (
                      <button
                        type="button"
                        onClick={handleRetryZipFailed}
                        disabled={isZipImporting}
                        className="flex items-center gap-1.5 px-4 py-2 rounded-xl text-xs sm:text-sm font-semibold border transition cursor-pointer active:scale-95"
                        style={{
                          backgroundColor: 'var(--warning-bg)',
                          borderColor: 'var(--warning)',
                          color: 'var(--warning)'
                        }}
                      >
                        <RefreshCw className="w-3.5 h-3.5" />
                        <span>Retry Failed ({zipJob.failed_count})</span>
                      </button>
                    )}

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
                  </>
                )}
              </div>
            </div>
          </div>
        ) : (
          /* ========================================================================= */
          /* VIEW 2: STANDARD SINGLE & MULTI-FILE UPLOAD WORKBENCH (UNTOUCHED LOGIC) */
          /* ========================================================================= */
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

            {/* Hidden multi-file input with ZIP and JSON enabled */}
            <input
              ref={fileInputRef}
              type="file"
              multiple
              onChange={handleFileChange}
              className="hidden"
              accept=".pdf,.docx,.txt,.md,.markdown,.csv,.xlsx,.xls,.png,.jpg,.jpeg,.tiff,.tif,.webp,.pptx,.ppt,.html,.htm,.zip,.json"
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

                {/* Supported format badges including ZIP, Slack, PPTX */}
                <div className="flex flex-wrap items-center justify-center gap-1.5 mt-3 pt-3 border-t border-[var(--border-color)]/60 max-w-md">
                  {['ZIP Archive', 'Slack Export', 'PPTX', 'PDF', 'DOCX', 'XLSX', 'CSV', 'PNG / JPG', 'HTML', 'Markdown', 'JSON'].map(fmt => (
                    <span 
                      key={fmt} 
                      className={`text-[10px] font-medium px-2 py-0.5 rounded-md border ${
                        fmt === 'ZIP Archive' || fmt === 'Slack Export' ? 'border-[var(--brand-accent)]/40 text-[var(--brand-accent)] font-semibold' : ''
                      }`}
                      style={{
                        backgroundColor: 'var(--bg-surface)',
                        borderColor: fmt === 'ZIP Archive' ? undefined : 'var(--border-color)',
                        color: fmt === 'ZIP Archive' ? undefined : 'var(--text-secondary)'
                      }}
                    >
                      {fmt}
                    </span>
                  ))}
                </div>
              </div>
            </div>

            {/* Selected File List */}
            {fileList.length > 0 && (
              <div className="space-y-2">
                <div className="flex items-center justify-between text-xs font-semibold text-[var(--text-secondary)] px-1">
                  <span>Selected Documents ({fileList.length})</span>
                  <button
                    type="button"
                    onClick={handleClearAll}
                    disabled={isUploading}
                    className="text-[11px] text-[var(--text-muted)] hover:text-[var(--error)] transition cursor-pointer"
                  >
                    Clear All
                  </button>
                </div>

                <div 
                  className="border rounded-2xl divide-y max-h-56 overflow-y-auto"
                  style={{
                    backgroundColor: 'var(--bg-surface)',
                    borderColor: 'var(--border-color)',
                  }}
                >
                  {fileList.map((item) => {
                    const badge = getFormatBadge(item.file.name);
                    const BadgeIcon = badge.icon;
                    return (
                      <div key={item.id} className="p-3 flex items-center justify-between gap-3 text-xs">
                        <div className="flex items-center gap-2.5 min-w-0 flex-1">
                          <span className={`px-2 py-0.5 rounded-md border text-[10px] font-bold flex items-center gap-1 ${badge.color}`}>
                            <BadgeIcon className="w-3 h-3" />
                            <span>{badge.label}</span>
                          </span>
                          <div className="min-w-0 flex-1">
                            <input
                              type="text"
                              value={item.title}
                              disabled={isUploading || item.status === 'completed'}
                              onChange={(e) => handleTitleChange(item.id, e.target.value)}
                              className="font-medium text-xs w-full bg-transparent border-b border-transparent hover:border-[var(--border-color)] focus:border-[var(--brand-accent)] focus:outline-none transition py-0.5 text-[var(--text-primary)]"
                              placeholder="Document title"
                            />
                            <div className="flex items-center gap-2 text-[10px] text-[var(--text-muted)] font-mono">
                              <span>{(item.sizeBytes / 1024).toFixed(1)} KB</span>
                              {item.sha256 && (
                                <span className="truncate max-w-[140px]" title={item.sha256}>
                                  SHA: {item.sha256.substring(0, 10)}...
                                </span>
                              )}
                            </div>
                          </div>
                        </div>

                        {/* Status / Remove Action */}
                        <div className="flex items-center gap-2 flex-shrink-0">
                          {item.status === 'completed' && (
                            <span className="text-[11px] text-[var(--success)] font-semibold flex items-center gap-1">
                              <CheckCircle2 className="w-3.5 h-3.5" />
                              <span>Ready</span>
                            </span>
                          )}
                          {item.status === 'failed' && (
                            <span className="text-[11px] text-[var(--error)] font-semibold flex items-center gap-1" title={item.error}>
                              <AlertCircle className="w-3.5 h-3.5" />
                              <span>Failed</span>
                            </span>
                          )}
                          {item.status === 'uploading' && (
                            <div className="w-4 h-4 border-2 border-[var(--brand-accent)]/30 border-t-[var(--brand-accent)] rounded-full animate-spin" />
                          )}
                          {item.status === 'pending' && !isUploading && (
                            <button
                              type="button"
                              onClick={() => handleRemoveFile(item.id)}
                              className="p-1 rounded-lg hover:bg-[var(--bg-surface-soft)] text-[var(--text-muted)] hover:text-[var(--error)] transition cursor-pointer"
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

            {/* Target Collection & Authority Selection */}
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
        )}
      </div>
    </div>
  );
};
