'use client';

import React, { useState, useRef } from 'react';
import { X, Upload, FileText, AlertCircle, Shield, Hash, ArrowRight } from 'lucide-react';
import { Collection, api } from '@/lib/api';
import { useI18n } from '@/lib/i18n';

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
  const [file, setFile] = useState<File | null>(null);
  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');
  const [collectionId, setCollectionId] = useState('');
  const [authorityLevel, setAuthorityLevel] = useState(3);
  const [fileHash, setFileHash] = useState('');
  const [isUploading, setIsUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fileInputRef = useRef<HTMLInputElement>(null);

  if (!isOpen) return null;

  const calculateSHA256 = async (selectedFile: File) => {
    try {
      const buffer = await selectedFile.arrayBuffer();
      const hashBuffer = await window.crypto.subtle.digest('SHA-256', buffer);
      const hashArray = Array.from(new Uint8Array(hashBuffer));
      const hashHex = hashArray.map(b => b.toString(16).padStart(2, '0')).join('');
      setFileHash(hashHex);
    } catch (err) {
      console.warn("SHA-256 computation error:", err);
    }
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const selected = e.target.files?.[0];
    if (selected) {
      setFile(selected);
      setTitle(selected.name.replace(/\.[^/.]+$/, ""));
      setError(null);
      calculateSHA256(selected);
    }
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    const dropped = e.dataTransfer.files?.[0];
    if (dropped) {
      setFile(dropped);
      setTitle(dropped.name.replace(/\.[^/.]+$/, ""));
      setError(null);
      calculateSHA256(dropped);
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!file) {
      setError('Please select a document to upload.');
      return;
    }

    setIsUploading(true);
    setError(null);

    try {
      const formData = new FormData();
      formData.append('file', file);
      formData.append('workspace', workspaceId);
      formData.append('title', title || file.name);
      formData.append('description', description);
      formData.append('authority_level', authorityLevel.toString());
      if (collectionId) {
        formData.append('collection', collectionId);
      }

      const res = await api.uploadDocument(formData);
      onUploadSuccess(res.document.id, res.job_id);
      onClose();
    } catch (err: any) {
      setError(err.message || 'Failed to upload document.');
    } finally {
      setIsUploading(false);
    }
  };

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
      className="fixed inset-0 z-50 flex items-center justify-center p-4 backdrop-blur-sm"
      style={{ backgroundColor: 'var(--modal-overlay)' }}
    >
      <div 
        className="w-full max-w-xl rounded-2xl border shadow-2xl overflow-hidden flex flex-col max-h-[90vh] animate-in fade-in zoom-in-95 duration-150"
        style={{
          backgroundColor: 'var(--bg-surface)',
          borderColor: 'var(--border-color)',
        }}
      >
        {/* Modal Header */}
        <div 
          className="flex items-center justify-between px-6 py-4 border-b"
          style={{ borderColor: 'var(--border-color)' }}
        >
          <div className="flex items-center gap-2.5">
            <div 
              className="w-8 h-8 rounded-xl flex items-center justify-center border"
              style={{
                backgroundColor: 'var(--accent-light)',
                borderColor: 'var(--border-color)',
                color: 'var(--brand-accent)',
              }}
            >
              <Upload className="w-4 h-4" />
            </div>
            <div>
              <h3 className="text-sm sm:text-base font-bold text-[var(--text-primary)]">
                {t('upload.modal_title')}
              </h3>
              <p className="text-xs text-[var(--text-muted)]">
                {t('upload.supported_formats')}
              </p>
            </div>
          </div>
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

        {/* Form Body */}
        <form onSubmit={handleSubmit} className="p-6 space-y-4 overflow-y-auto flex-1">
          {error && (
            <div 
              className="p-3 rounded-xl border text-xs flex items-center gap-2"
              style={{
                backgroundColor: 'var(--error-bg)',
                borderColor: 'var(--border-color)',
                color: 'var(--error)',
              }}
            >
              <AlertCircle className="w-4 h-4 flex-shrink-0" />
              <span>{error}</span>
            </div>
          )}

          {/* Drag & Drop Zone */}
          <div
            onDragOver={(e) => e.preventDefault()}
            onDrop={handleDrop}
            onClick={() => fileInputRef.current?.click()}
            className="border-2 border-dashed rounded-2xl p-6 text-center cursor-pointer transition-all duration-200"
            style={{
              backgroundColor: file ? 'var(--accent-light)' : 'var(--bg-surface-soft)',
              borderColor: file ? 'var(--brand-accent)' : 'var(--border-color)',
            }}
          >
            <input
              ref={fileInputRef}
              type="file"
              onChange={handleFileChange}
              className="hidden"
              accept=".pdf,.docx,.txt,.md,.markdown,.csv,.xlsx,.xls,.png,.jpg,.jpeg,.pptx"
            />
            {file ? (
              <div className="flex flex-col items-center">
                <FileText className="w-10 h-10 mb-2 text-[var(--brand-accent)]" />
                <span className="text-sm font-bold text-[var(--text-primary)]">{file.name}</span>
                <span className="text-xs text-[var(--text-muted)] mt-0.5">
                  {(file.size / 1024 / 1024).toFixed(2)} MB • {file.type || 'Document'}
                </span>
                {fileHash && (
                  <div 
                    className="flex items-center gap-1.5 mt-2.5 text-[11px] font-mono px-2.5 py-1 rounded-lg border max-w-full truncate"
                    style={{
                      backgroundColor: 'var(--accent-light)',
                      borderColor: 'var(--border-color)',
                      color: 'var(--brand-accent)',
                    }}
                  >
                    <Hash className="w-3 h-3 flex-shrink-0" />
                    <span className="truncate">SHA-256: {fileHash}</span>
                  </div>
                )}
              </div>
            ) : (
              <div className="flex flex-col items-center">
                <Upload className="w-10 h-10 mb-2 text-[var(--brand-accent)]" />
                <span className="text-sm font-semibold text-[var(--text-primary)]">
                  {t('upload.drag_drop')}
                </span>
                <span className="text-xs text-[var(--text-muted)] mt-1">
                  {t('upload.or_browse')}
                </span>
              </div>
            )}
          </div>

          {/* Title & Collection */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div>
              <label className="block text-xs font-semibold text-[var(--text-secondary)] mb-1">
                {t('docs.title')}
              </label>
              <input
                type="text"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                placeholder="e.g. Land Deed CS-4819"
                className="w-full border rounded-xl px-3 py-2 text-xs sm:text-sm focus:outline-none"
                style={{
                  backgroundColor: 'var(--input-bg)',
                  borderColor: 'var(--input-border)',
                  color: 'var(--text-primary)',
                }}
              />
            </div>
            <div>
              <label className="block text-xs font-semibold text-[var(--text-secondary)] mb-1">
                {t('upload.collection_label')}
              </label>
              <select
                value={collectionId}
                onChange={(e) => setCollectionId(e.target.value)}
                className="w-full border rounded-xl px-3 py-2 text-xs sm:text-sm focus:outline-none cursor-pointer"
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
          </div>

          {/* Authority Ladder Selection */}
          <div>
            <label className="block text-xs font-semibold text-[var(--text-secondary)] mb-1 flex items-center justify-between">
              <span className="flex items-center gap-1.5">
                <Shield className="w-3.5 h-3.5 text-[var(--brand-accent)]" />
                <span>Source Authority Ladder (LORE L6)</span>
              </span>
              <span className="text-[11px] text-[var(--text-muted)]">Rank determines conflict priority</span>
            </label>
            <select
              value={authorityLevel}
              onChange={(e) => setAuthorityLevel(Number(e.target.value))}
              className="w-full border rounded-xl px-3 py-2 text-xs sm:text-sm focus:outline-none cursor-pointer"
              style={{
                backgroundColor: 'var(--input-bg)',
                borderColor: 'var(--input-border)',
                color: 'var(--text-primary)',
              }}
            >
              {authorityLadder.map(item => (
                <option key={item.rank} value={item.rank}>
                  {item.label} — {item.desc}
                </option>
              ))}
            </select>
          </div>

          {/* Description */}
          <div>
            <label className="block text-xs font-semibold text-[var(--text-secondary)] mb-1">
              Description (Optional)
            </label>
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="Notes, party names, deed registry notes..."
              rows={2}
              className="w-full border rounded-xl px-3 py-2 text-xs sm:text-sm focus:outline-none resize-none"
              style={{
                backgroundColor: 'var(--input-bg)',
                borderColor: 'var(--input-border)',
                color: 'var(--text-primary)',
              }}
            />
          </div>

          {/* Action Buttons */}
          <div 
            className="pt-3 flex items-center justify-end gap-3 border-t"
            style={{ borderColor: 'var(--border-color)' }}
          >
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
              {t('common.cancel')}
            </button>
            <button
              type="submit"
              disabled={!file || isUploading}
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
                  <span>{t('upload.start_btn')}</span>
                  <ArrowRight className="w-4 h-4" />
                </>
              )}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};
