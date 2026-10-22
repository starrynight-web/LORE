'use client';

import React, { useState } from 'react';
import { 
  FileText, 
  Search, 
  Filter, 
  CheckCircle2, 
  Clock, 
  AlertTriangle, 
  XCircle, 
  Shield, 
  ExternalLink,
  ChevronRight,
  RefreshCw,
  Folder
} from 'lucide-react';
import { SourceDocument, Collection } from '@/lib/api';

interface DocumentListProps {
  documents: SourceDocument[];
  collections: Collection[];
  onSelectDocument: (doc: SourceDocument) => void;
  onRefresh: () => void;
}

export const DocumentList: React.FC<DocumentListProps> = ({
  documents,
  collections,
  onSelectDocument,
  onRefresh
}) => {
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
          <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
            <CheckCircle2 className="w-3 h-3" />
            <span>Ready</span>
          </span>
        );
      case 'extracting':
      case 'normalizing':
      case 'chunking':
      case 'embedding':
      case 'indexing':
        return (
          <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-blue-500/10 text-blue-400 border border-blue-500/20 animate-pulse">
            <Clock className="w-3 h-3" />
            <span className="capitalize">{status}</span>
          </span>
        );
      case 'needs_review':
        return (
          <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-amber-500/10 text-amber-400 border border-amber-500/20">
            <AlertTriangle className="w-3 h-3" />
            <span>Needs Review</span>
          </span>
        );
      case 'quarantined':
        return (
          <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-purple-500/10 text-purple-400 border border-purple-500/20">
            <Shield className="w-3 h-3" />
            <span>Quarantined</span>
          </span>
        );
      case 'failed':
        return (
          <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-rose-500/10 text-rose-400 border border-rose-500/20">
            <XCircle className="w-3 h-3" />
            <span>Failed</span>
          </span>
        );
      default:
        return (
          <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-slate-700 text-slate-300">
            <span>{status}</span>
          </span>
        );
    }
  };

  const getAuthorityBadge = (level: number) => {
    const map: Record<number, { label: string; color: string }> = {
      7: { label: 'Approved Policy (R7)', color: 'border-indigo-500/30 text-indigo-400 bg-indigo-500/10' },
      6: { label: 'Signed Contract (R6)', color: 'border-emerald-500/30 text-emerald-400 bg-emerald-500/10' },
      5: { label: 'Team Convention (R5)', color: 'border-cyan-500/30 text-cyan-400 bg-cyan-500/10' },
      4: { label: 'Procedure (R4)', color: 'border-blue-500/30 text-blue-400 bg-blue-500/10' },
      3: { label: 'Reviewed Doc (R3)', color: 'border-slate-500/30 text-slate-400 bg-slate-500/10' },
      2: { label: 'Wiki Entry (R2)', color: 'border-amber-500/30 text-amber-400 bg-amber-500/10' },
      1: { label: 'Informal Note (R1)', color: 'border-orange-500/30 text-orange-400 bg-orange-500/10' },
    };
    const item = map[level] || map[3];
    return (
      <span className={`text-[11px] font-semibold px-2 py-0.5 rounded border ${item.color}`}>
        {item.label}
      </span>
    );
  };

  return (
    <div className="space-y-4">
      {/* Search & Filter Bar */}
      <div className="flex flex-col sm:flex-row items-center justify-between gap-3 bg-slate-900/60 p-4 rounded-xl border border-slate-800">
        <div className="flex items-center gap-2.5 w-full sm:w-96 bg-slate-800 border border-slate-700/60 px-3 py-2 rounded-lg text-sm text-slate-300">
          <Search className="w-4 h-4 text-slate-400" />
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Filter documents by title, filename..."
            className="w-full bg-transparent focus:outline-none text-white text-sm"
          />
        </div>

        <div className="flex items-center gap-2 w-full sm:w-auto">
          {/* Collection Filter */}
          <select
            value={selectedCollection}
            onChange={(e) => setSelectedCollection(e.target.value)}
            className="bg-slate-800 border border-slate-700/60 rounded-lg px-3 py-2 text-xs text-slate-300 focus:outline-none"
          >
            <option value="all">All Collections</option>
            {collections.map(c => (
              <option key={c.id} value={c.id}>{c.name}</option>
            ))}
          </select>

          {/* Status Filter */}
          <select
            value={selectedStatus}
            onChange={(e) => setSelectedStatus(e.target.value)}
            className="bg-slate-800 border border-slate-700/60 rounded-lg px-3 py-2 text-xs text-slate-300 focus:outline-none"
          >
            <option value="all">All Statuses</option>
            <option value="ready">Ready</option>
            <option value="extracting">Processing</option>
            <option value="needs_review">Needs Review</option>
            <option value="quarantined">Quarantined</option>
            <option value="failed">Failed</option>
          </select>

          <button
            onClick={onRefresh}
            className="p-2 bg-slate-800 hover:bg-slate-700 border border-slate-700 rounded-lg text-slate-400 hover:text-white transition cursor-pointer"
            title="Refresh documents"
          >
            <RefreshCw className="w-4 h-4" />
          </button>
        </div>
      </div>

      {/* Documents Table */}
      <div className="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden shadow-xl">
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm text-slate-300">
            <thead className="bg-slate-800/60 text-xs font-semibold uppercase tracking-wider text-slate-400 border-b border-slate-800">
              <tr>
                <th className="px-6 py-3.5">Document</th>
                <th className="px-4 py-3.5">Collection</th>
                <th className="px-4 py-3.5">Authority Ladder</th>
                <th className="px-4 py-3.5">Processing Status</th>
                <th className="px-4 py-3.5">OCR Conf.</th>
                <th className="px-4 py-3.5 text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800">
              {filteredDocs.length === 0 ? (
                <tr>
                  <td colSpan={6} className="px-6 py-12 text-center text-slate-500 text-sm">
                    No documents found matching your filter.
                  </td>
                </tr>
              ) : (
                filteredDocs.map((doc) => (
                  <tr
                    key={doc.id}
                    onClick={() => onSelectDocument(doc)}
                    className="hover:bg-slate-800/40 cursor-pointer transition group"
                  >
                    <td className="px-6 py-4">
                      <div className="flex items-center gap-3">
                        <div className="w-9 h-9 rounded-lg bg-indigo-500/10 text-indigo-400 border border-indigo-500/20 flex items-center justify-center flex-shrink-0">
                          <FileText className="w-4 h-4" />
                        </div>
                        <div>
                          <div className="font-semibold text-white group-hover:text-indigo-400 transition">
                            {doc.title}
                          </div>
                          <div className="text-xs text-slate-400">
                            {doc.original_filename} • {(doc.file_size / 1024).toFixed(1)} KB • {doc.page_count} pg
                          </div>
                        </div>
                      </div>
                    </td>

                    <td className="px-4 py-4">
                      {doc.collection_name ? (
                        <span className="inline-flex items-center gap-1.5 text-xs text-slate-300">
                          <Folder className="w-3.5 h-3.5 text-indigo-400" />
                          <span>{doc.collection_name}</span>
                        </span>
                      ) : (
                        <span className="text-xs text-slate-400">—</span>
                      )}
                    </td>

                    <td className="px-4 py-4">
                      {getAuthorityBadge(doc.authority_level)}
                    </td>

                    <td className="px-4 py-4">
                      {getStatusBadge(doc.status)}
                    </td>

                    <td className="px-4 py-4 font-mono text-xs">
                      {doc.ocr_confidence > 0 ? (
                        <span className={doc.ocr_confidence >= 0.70 ? 'text-emerald-400' : 'text-amber-400'}>
                          {(doc.ocr_confidence * 100).toFixed(1)}%
                        </span>
                      ) : (
                        <span className="text-slate-400">Digital</span>
                      )}
                    </td>

                    <td className="px-4 py-4 text-right">
                      <button className="text-slate-400 group-hover:text-white p-1 hover:bg-slate-700/50 rounded transition">
                        <ChevronRight className="w-4 h-4" />
                      </button>
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
