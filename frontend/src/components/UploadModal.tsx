'use client';

import React, { useState, useRef } from 'react';
import { X, Upload, FileText, CheckCircle2, AlertCircle, Shield, Hash, ArrowRight } from 'lucide-react';
import { Collection, api } from '@/lib/api';

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
  const [file, setFile] = useState<File | null>(null);
  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');
  const [collectionId, setCollectionId] = useState('');
  const [authorityLevel, setAuthorityLevel] = useState(3);
  const [fileHash, setFileHash] = useState('');
  const [isCalculatingHash, setIsCalculatingHash] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fileInputRef = useRef<HTMLInputElement>(null);

  if (!isOpen) return null;

  const calculateSHA256 = async (selectedFile: File) => {
    setIsCalculatingHash(true);
    try {
      const buffer = await selectedFile.arrayBuffer();
      const hashBuffer = await window.crypto.subtle.digest('SHA-256', buffer);
      const hashArray = Array.from(new Uint8Array(hashBuffer));
      const hashHex = hashArray.map(b => b.toString(16).padStart(2, '0')).join('');
      setFileHash(hashHex);
    } catch (err) {
      console.warn("SHA-256 computation error:", err);
    } finally {
      setIsCalculatingHash(false);
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
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4">
      <div className="bg-slate-900 border border-slate-800 w-full max-w-xl rounded-2xl shadow-2xl overflow-hidden flex flex-col max-h-[90vh]">
        {/* Modal Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-800">
          <div className="flex items-center gap-2.5">
            <div className="w-8 h-8 rounded-lg bg-indigo-600/20 text-indigo-400 flex items-center justify-center">
              <Upload className="w-4 h-4" />
            </div>
            <div>
              <h3 className="text-base font-semibold text-white">Upload Knowledge Document</h3>
              <p className="text-xs text-slate-400">PDF, DOCX, XLSX, TXT, MD, PNG, JPEG</p>
            </div>
          </div>
          <button 
            onClick={onClose}
            className="text-slate-400 hover:text-white p-1 rounded-lg hover:bg-slate-800 transition"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Form Body */}
        <form onSubmit={handleSubmit} className="p-6 space-y-4 overflow-y-auto flex-1">
          {error && (
            <div className="p-3 rounded-lg bg-rose-500/10 border border-rose-500/30 text-rose-400 text-xs flex items-center gap-2">
              <AlertCircle className="w-4 h-4 flex-shrink-0" />
              <span>{error}</span>
            </div>
          )}

          {/* Drag & Drop Zone */}
          <div
            onDragOver={(e) => e.preventDefault()}
            onDrop={handleDrop}
            onClick={() => fileInputRef.current?.click()}
            className={`border-2 border-dashed rounded-xl p-6 text-center cursor-pointer transition ${
              file
                ? 'border-indigo-500/50 bg-indigo-500/5'
                : 'border-slate-700 hover:border-slate-500 bg-slate-800/30'
            }`}
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
                <FileText className="w-10 h-10 text-indigo-400 mb-2" />
                <span className="text-sm font-semibold text-white">{file.name}</span>
                <span className="text-xs text-slate-400 mt-0.5">
                  {(file.size / 1024 / 1024).toFixed(2)} MB • {file.type || 'Document'}
                </span>
                {fileHash && (
                  <div className="flex items-center gap-1.5 mt-2.5 text-[11px] font-mono text-emerald-400 bg-emerald-500/10 px-2.5 py-1 rounded-md border border-emerald-500/20 max-w-full truncate">
                    <Hash className="w-3 h-3 flex-shrink-0" />
                    <span className="truncate">SHA-256: {fileHash}</span>
                  </div>
                )}
              </div>
            ) : (
              <div className="flex flex-col items-center">
                <Upload className="w-10 h-10 text-slate-500 mb-2" />
                <span className="text-sm font-medium text-slate-200">
                  Click to select or drag and drop document
                </span>
                <span className="text-xs text-slate-500 mt-1">
                  Enforces magic byte verification & OCR for scanned pages
                </span>
              </div>
            )}
          </div>

          {/* Title & Collection */}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs font-medium text-slate-300 mb-1">Document Title</label>
              <input
                type="text"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                placeholder="e.g. Cloud Security Policy v3.0"
                className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-indigo-500"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-slate-300 mb-1">Collection</label>
              <select
                value={collectionId}
                onChange={(e) => setCollectionId(e.target.value)}
                className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-indigo-500"
              >
                <option value="">No Collection (Root)</option>
                {collections.map(c => (
                  <option key={c.id} value={c.id}>{c.name}</option>
                ))}
              </select>
            </div>
          </div>

          {/* Authority Ladder Selection */}
          <div>
            <label className="block text-xs font-medium text-slate-300 mb-1 flex items-center justify-between">
              <span className="flex items-center gap-1.5">
                <Shield className="w-3.5 h-3.5 text-indigo-400" />
                <span>Source Authority Ladder (LORE L6)</span>
              </span>
              <span className="text-[11px] text-slate-400">Rank determines conflict resolution</span>
            </label>
            <select
              value={authorityLevel}
              onChange={(e) => setAuthorityLevel(Number(e.target.value))}
              className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-indigo-500"
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
            <label className="block text-xs font-medium text-slate-300 mb-1">Description (Optional)</label>
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="Context, effective scope, or owner notes..."
              rows={2}
              className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-indigo-500 resize-none"
            />
          </div>

          {/* Action Buttons */}
          <div className="pt-2 flex items-center justify-end gap-3 border-t border-slate-800">
            <button
              type="button"
              onClick={onClose}
              disabled={isUploading}
              className="px-4 py-2 text-sm text-slate-400 hover:text-white rounded-lg transition"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={!file || isUploading}
              className="flex items-center gap-2 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white px-5 py-2 rounded-lg text-sm font-semibold shadow-md shadow-indigo-600/30 transition cursor-pointer"
            >
              {isUploading ? (
                <>
                  <div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                  <span>Processing...</span>
                </>
              ) : (
                <>
                  <span>Upload & Ingest</span>
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
