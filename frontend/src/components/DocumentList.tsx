'use client';

import React, { useState } from 'react';
import { 
  FileText, 
  Search, 
  CheckCircle2, 
  Clock, 
  AlertTriangle, 
  XCircle, 
  Shield, 
  ChevronRight,
  RefreshCw,
  Folder,
  Sparkles
} from 'lucide-react';
import { SourceDocument, Collection } from '@/lib/api';
import { useI18n } from '@/lib/i18n';

interface DocumentListProps {
  documents: SourceDocument[];
  collections: Collection[];
  onSelectDocument: (doc: SourceDocument) => void;
  onRefresh: () => void;
  onAskAgent?: (docId: string) => void;
}

export const DocumentList: React.FC<DocumentListProps> = ({
  documents,
  collections,
  onSelectDocument,
  onRefresh,
  onAskAgent
}) => {
  const { t } = useI18n();
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedCollection, setSelectedCollection] = useState<string>('all');
  const [selectedStatus, setSelectedStatus] = useState<string>('all');

  const filteredDocs = documents.filter((doc) => {
    const matchesSearch = 
      doc.title.toLowerCase().includes(searchQuery.toLowerCase()) ||
      doc.original_filename.toLowerCase().includes(searchQuery.toLowerCase());
    const matchesCollection = 
      selectedCollection === 'all' || doc.collection === selectedCollection;
    const matchesStatus = 
      selectedStatus === 'all' || doc.status === selectedStatus;
    return matchesSearch && matchesCollection && matchesStatus;
  });

  const getStatusBadge = (status: string) => {
    switch (status) {
      case 'ready':
        return (
          <span 
            className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-semibold border"
            style={{
              backgroundColor: 'var(--success-bg)',
              color: 'var(--success)',
              borderColor: 'var(--border-color)',
            }}
          >
            <CheckCircle2 className="w-3 h-3" />
            <span>{t('common.ready')}</span>
          </span>
        );
      case 'extracting':
      case 'normalizing':
      case 'chunking':
      case 'embedding':
      case 'indexing':
        return (
          <span 
            className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-semibold border animate-pulse"
            style={{
              backgroundColor: 'var(--accent-light)',
              color: 'var(--brand-accent)',
              borderColor: 'var(--border-color)',
            }}
          >
            <Clock className="w-3 h-3" />
            <span className="capitalize">{status}</span>
          </span>
        );
      case 'needs_review':
        return (
          <span 
            className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-semibold border"
            style={{
              backgroundColor: 'var(--warning-bg)',
              color: 'var(--warning)',
              borderColor: 'var(--border-color)',
            }}
          >
            <AlertTriangle className="w-3 h-3" />
            <span>{t('common.needs_review')}</span>
          </span>
        );
      case 'quarantined':
        return (
          <span 
            className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-semibold border"
            style={{
              backgroundColor: 'var(--bg-surface-soft)',
              color: 'var(--text-secondary)',
              borderColor: 'var(--border-color)',
            }}
          >
            <Shield className="w-3 h-3" />
            <span>{t('common.quarantined')}</span>
          </span>
        );
      case 'failed':
        return (
          <span 
            className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-semibold border"
            style={{
              backgroundColor: 'var(--error-bg)',
              color: 'var(--error)',
              borderColor: 'var(--border-color)',
            }}
          >
            <XCircle className="w-3 h-3" />
            <span>{t('common.failed')}</span>
          </span>
        );
      default:
        return (
          <span 
            className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-semibold border"
            style={{
              backgroundColor: 'var(--badge-neutral-bg)',
              color: 'var(--badge-neutral-text)',
              borderColor: 'var(--badge-neutral-border)',
            }}
          >
            <span>{status}</span>
          </span>
        );
    }
  };

  const getAuthorityBadge = (level: number) => {
    const map: Record<number, { label: string }> = {
      7: { label: 'Policy (R7)' },
      6: { label: 'Signed Contract (R6)' },
      5: { label: 'Convention (R5)' },
      4: { label: 'Procedure (R4)' },
      3: { label: 'Reviewed Doc (R3)' },
      2: { label: 'Wiki Entry (R2)' },
      1: { label: 'Informal Note (R1)' },
    };
    const item = map[level] || map[3];
    return (
      <span 
        className="text-[11px] font-semibold px-2 py-0.5 rounded border"
        style={{
          backgroundColor: 'var(--bg-surface-soft)',
          borderColor: 'var(--border-color)',
          color: 'var(--text-secondary)',
        }}
      >
        {item.label}
      </span>
    );
  };

  return (
    <div className="space-y-4">
      {/* Search & Filter Bar */}
      <div 
        className="flex flex-col sm:flex-row items-center justify-between gap-3 p-4 rounded-2xl border shadow-sm"
        style={{
          backgroundColor: 'var(--bg-surface)',
          borderColor: 'var(--border-color)',
        }}
      >
        <div 
          className="flex items-center gap-2.5 w-full sm:w-96 border px-3.5 py-2 rounded-xl text-sm"
          style={{
            backgroundColor: 'var(--input-bg)',
            borderColor: 'var(--input-border)',
          }}
        >
          <Search className="w-4 h-4 text-[var(--text-muted)] shrink-0" />
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder={t('docs.search_placeholder')}
            className="w-full bg-transparent focus:outline-none text-xs sm:text-sm text-[var(--text-primary)] placeholder-[var(--text-muted)]"
          />
        </div>

        <div className="flex items-center gap-2 w-full sm:w-auto">
          {/* Collection Filter */}
          <select
            value={selectedCollection}
            onChange={(e) => setSelectedCollection(e.target.value)}
            className="border rounded-xl px-3 py-2 text-xs font-medium focus:outline-none cursor-pointer"
            style={{
              backgroundColor: 'var(--input-bg)',
              borderColor: 'var(--input-border)',
              color: 'var(--text-primary)',
            }}
          >
            <option value="all">{t('docs.all_collections')}</option>
            {collections.map(c => (
              <option key={c.id} value={c.id}>{c.name}</option>
            ))}
          </select>

          {/* Status Filter */}
          <select
            value={selectedStatus}
            onChange={(e) => setSelectedStatus(e.target.value)}
            className="border rounded-xl px-3 py-2 text-xs font-medium focus:outline-none cursor-pointer"
            style={{
              backgroundColor: 'var(--input-bg)',
              borderColor: 'var(--input-border)',
              color: 'var(--text-primary)',
            }}
          >
            <option value="all">{t('docs.all_statuses')}</option>
            <option value="ready">{t('common.ready')}</option>
            <option value="extracting">{t('common.processing')}</option>
            <option value="needs_review">{t('common.needs_review')}</option>
            <option value="quarantined">{t('common.quarantined')}</option>
            <option value="failed">{t('common.failed')}</option>
          </select>

          <button
            onClick={onRefresh}
            className="p-2 border rounded-xl transition-all cursor-pointer hover:border-[var(--brand-accent)] active:scale-95"
            style={{
              backgroundColor: 'var(--bg-surface-soft)',
              borderColor: 'var(--border-color)',
              color: 'var(--text-secondary)',
            }}
            title={t('common.refresh')}
          >
            <RefreshCw className="w-4 h-4" />
          </button>
        </div>
      </div>

      {/* Documents Table */}
      <div 
        className="rounded-2xl border overflow-hidden shadow-sm"
        style={{
          backgroundColor: 'var(--bg-surface)',
          borderColor: 'var(--border-color)',
        }}
      >
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs sm:text-sm">
            <thead 
              className="text-xs font-bold uppercase tracking-wider border-b"
              style={{
                backgroundColor: 'var(--table-header-bg)',
                borderColor: 'var(--border-color)',
                color: 'var(--text-muted)',
              }}
            >
              <tr>
                <th className="px-5 py-3.5">{t('docs.title')}</th>
                <th className="px-4 py-3.5">{t('docs.collection')}</th>
                <th className="px-4 py-3.5">Authority Rank</th>
                <th className="px-4 py-3.5">{t('common.status')}</th>
                <th className="px-4 py-3.5">OCR Conf.</th>
                <th className="px-4 py-3.5 text-right">{t('common.actions')}</th>
              </tr>
            </thead>
            <tbody className="divide-y" style={{ borderColor: 'var(--border-color)' }}>
              {filteredDocs.length === 0 ? (
                <tr>
                  <td colSpan={6} className="px-6 py-12 text-center text-sm text-[var(--text-muted)]">
                    {t('docs.empty_title')}
                  </td>
                </tr>
              ) : (
                filteredDocs.map((doc) => (
                  <tr
                    key={doc.id}
                    onClick={() => onSelectDocument(doc)}
                    className="cursor-pointer transition-colors duration-150 group"
                    style={{
                      borderBottomColor: 'var(--border-color)',
                    }}
                    onMouseEnter={(e) => (e.currentTarget.style.backgroundColor = 'var(--table-row-hover)')}
                    onMouseLeave={(e) => (e.currentTarget.style.backgroundColor = 'transparent')}
                  >
                    <td className="px-5 py-3.5">
                      <div className="flex items-center gap-3">
                        <div 
                          className="w-9 h-9 rounded-xl border flex items-center justify-center flex-shrink-0"
                          style={{
                            backgroundColor: 'var(--accent-light)',
                            borderColor: 'var(--border-color)',
                            color: 'var(--brand-accent)',
                          }}
                        >
                          <FileText className="w-4 h-4" />
                        </div>
                        <div className="min-w-0">
                          <div className="font-semibold text-xs sm:text-sm text-[var(--text-primary)] group-hover:text-[var(--brand-accent)] transition truncate max-w-sm">
                            {doc.title}
                          </div>
                          <div className="text-[11px] text-[var(--text-muted)] truncate">
                            {doc.original_filename} • {(doc.file_size / 1024).toFixed(1)} KB • {doc.page_count} pg
                          </div>
                        </div>
                      </div>
                    </td>

                    <td className="px-4 py-3.5">
                      {doc.collection_name ? (
                        <span className="inline-flex items-center gap-1.5 text-xs text-[var(--text-secondary)]">
                          <Folder className="w-3.5 h-3.5 text-[var(--brand-accent)]" />
                          <span>{doc.collection_name}</span>
                        </span>
                      ) : (
                        <span className="text-xs text-[var(--text-muted)]">—</span>
                      )}
                    </td>

                    <td className="px-4 py-3.5">
                      {getAuthorityBadge(doc.authority_level)}
                    </td>

                    <td className="px-4 py-3.5">
                      {getStatusBadge(doc.status)}
                    </td>

                    <td className="px-4 py-3.5 font-mono text-xs">
                      {doc.ocr_confidence > 0 ? (
                        <span className={doc.ocr_confidence >= 0.70 ? 'text-[var(--success)] font-bold' : 'text-[var(--warning)] font-bold'}>
                          {(doc.ocr_confidence * 100).toFixed(1)}%
                        </span>
                      ) : (
                        <span className="text-[var(--text-muted)]">Digital</span>
                      )}
                    </td>

                    <td className="px-4 py-3.5 text-right">
                      <div className="flex items-center justify-end gap-1.5">
                        {onAskAgent && (
                          <button
                            type="button"
                            onClick={(e) => {
                              e.stopPropagation();
                              onAskAgent(doc.id);
                            }}
                            title="Ask Governed Agent about this PDF"
                            className="px-2.5 py-1 rounded-lg text-xs font-semibold border flex items-center gap-1 transition-all cursor-pointer active:scale-95"
                            style={{
                              backgroundColor: 'var(--accent-light)',
                              borderColor: 'var(--border-color)',
                              color: 'var(--brand-accent)',
                            }}
                          >
                            <Sparkles className="w-3.5 h-3.5" />
                            <span className="hidden sm:inline">Ask Agent</span>
                          </button>
                        )}
                        <button 
                          className="p-1 rounded-lg transition"
                          style={{ color: 'var(--text-muted)' }}
                        >
                          <ChevronRight className="w-4 h-4 group-hover:text-[var(--brand-accent)]" />
                        </button>
                      </div>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
};
