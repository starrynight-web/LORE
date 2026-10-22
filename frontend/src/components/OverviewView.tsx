'use client';

import React from 'react';
import { 
  FileText, 
  Cpu, 
  AlertTriangle, 
  Search, 
  ShieldCheck, 
  CheckCircle2, 
  Upload,
  ArrowRight,
  Layers,
  Sparkles
} from 'lucide-react';
import { SourceDocument, IngestionJob } from '@/lib/api';
import { useI18n } from '@/lib/i18n';

interface OverviewViewProps {
  documents: SourceDocument[];
  jobs: IngestionJob[];
  onOpenUpload: () => void;
  onNavigate: (tab: string) => void;
}

export const OverviewView: React.FC<OverviewViewProps> = ({
  documents,
  jobs,
  onOpenUpload,
  onNavigate
}) => {
  const { t } = useI18n();

  const readyDocs = documents.filter(d => d.status === 'ready').length;
  const reviewDocs = documents.filter(d => d.status === 'needs_review' || d.status === 'quarantined').length;
  const activeJobs = jobs.filter(j => j.status !== 'ready' && j.status !== 'failed').length;

  return (
    <div className="space-y-6">
      {/* Restrained Enterprise Hero Surface (Parrot & Cream) */}
      <div 
        className="relative overflow-hidden rounded-2xl p-6 sm:p-8 border shadow-sm transition-all duration-200"
        style={{
          backgroundColor: 'var(--bg-surface)',
          borderColor: 'var(--border-color)',
        }}
      >
        <div className="relative z-10 max-w-3xl">
          <div 
            className="inline-flex items-center gap-2 px-3 py-1 rounded-full text-xs font-semibold border mb-3"
            style={{
              backgroundColor: 'var(--accent-light)',
              borderColor: 'var(--border-color)',
              color: 'var(--brand-accent)',
            }}
          >
            <Sparkles className="w-3.5 h-3.5" />
            <span>{t('overview.badge')}</span>
          </div>
          <h1 className="text-xl sm:text-2xl lg:text-3xl font-extrabold tracking-tight text-[var(--text-primary)]">
            {t('overview.hero_title')}
          </h1>
          <p className="mt-2 text-xs sm:text-sm text-[var(--text-secondary)] leading-relaxed">
            {t('overview.hero_desc')}
          </p>

          <div className="mt-5 flex flex-wrap items-center gap-3">
            <button
              onClick={onOpenUpload}
              className="flex items-center gap-2 px-4 py-2 rounded-xl text-xs sm:text-sm font-semibold shadow-sm transition-all duration-200 cursor-pointer active:scale-95"
              style={{
                backgroundColor: 'var(--brand-accent)',
                color: 'var(--cta-text)',
              }}
            >
              <Upload className="w-4 h-4" />
              <span>{t('header.upload_button')}</span>
            </button>
            <button
              onClick={() => onNavigate('rag')}
              className="flex items-center gap-2 px-4 py-2 rounded-xl text-xs sm:text-sm font-semibold border transition-all duration-200 cursor-pointer active:scale-95"
              style={{
                backgroundColor: 'var(--bg-surface-soft)',
                borderColor: 'var(--border-color)',
                color: 'var(--text-primary)',
              }}
            >
              <Search className="w-4 h-4 text-[var(--brand-accent)]" />
              <span>{t('overview.ask_rag')}</span>
            </button>
          </div>
        </div>
      </div>

      {/* KPI Metric Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {/* Total Documents */}
        <div 
          className="rounded-2xl p-5 border shadow-sm transition-all duration-200"
          style={{
            backgroundColor: 'var(--bg-surface)',
            borderColor: 'var(--border-color)',
          }}
        >
          <div className="flex items-center justify-between text-xs font-bold uppercase tracking-wider mb-2 text-[var(--text-muted)]">
            <span>{t('overview.total_documents')}</span>
            <FileText className="w-4 h-4 text-[var(--brand-accent)]" />
          </div>
          <div className="text-2xl font-extrabold text-[var(--text-primary)]">{documents.length}</div>
          <div className="text-xs text-[var(--text-secondary)] mt-1.5 flex items-center gap-1.5">
            <CheckCircle2 className="w-3.5 h-3.5 text-[var(--success)]" />
            <span>{readyDocs} {t('overview.ready_searchable')}</span>
          </div>
        </div>

        {/* Processing Jobs */}
        <div 
          className="rounded-2xl p-5 border shadow-sm transition-all duration-200"
          style={{
            backgroundColor: 'var(--bg-surface)',
            borderColor: 'var(--border-color)',
          }}
        >
          <div className="flex items-center justify-between text-xs font-bold uppercase tracking-wider mb-2 text-[var(--text-muted)]">
            <span>{t('overview.processing_jobs')}</span>
            <Cpu className="w-4 h-4 text-[var(--brand-accent)]" />
          </div>
          <div className="text-2xl font-extrabold text-[var(--text-primary)]">{jobs.length}</div>
          <div className="text-xs mt-1.5">
            {activeJobs > 0 ? (
              <span className="text-[var(--brand-accent)] font-semibold animate-pulse">
                {activeJobs} {t('overview.active_workers')}
              </span>
            ) : (
              <span className="text-[var(--text-muted)]">{t('overview.pipeline_idle')}</span>
            )}
          </div>
        </div>

        {/* Review Queue */}
        <div 
          className="rounded-2xl p-5 border shadow-sm transition-all duration-200"
          style={{
            backgroundColor: 'var(--bg-surface)',
            borderColor: 'var(--border-color)',
          }}
        >
          <div className="flex items-center justify-between text-xs font-bold uppercase tracking-wider mb-2 text-[var(--text-muted)]">
            <span>{t('overview.needs_review')}</span>
            <AlertTriangle className="w-4 h-4 text-[var(--warning)]" />
          </div>
          <div className="text-2xl font-extrabold text-[var(--text-primary)]">{reviewDocs}</div>
          <div className="text-xs mt-1.5">
            {reviewDocs > 0 ? (
              <span className="text-[var(--warning)] font-semibold">
                {t('overview.flagged_verification')}
              </span>
            ) : (
              <span className="text-[var(--success)] font-medium">All sources verified</span>
            )}
          </div>
        </div>

        {/* Governance State */}
        <div 
          className="rounded-2xl p-5 border shadow-sm transition-all duration-200"
          style={{
            backgroundColor: 'var(--bg-surface)',
            borderColor: 'var(--border-color)',
          }}
        >
          <div className="flex items-center justify-between text-xs font-bold uppercase tracking-wider mb-2 text-[var(--text-muted)]">
            <span>Governance Gate</span>
            <ShieldCheck className="w-4 h-4 text-[var(--success)]" />
          </div>
          <div className="text-base font-extrabold text-[var(--brand-accent)]">9-State Active</div>
          <div className="text-xs text-[var(--text-muted)] mt-1.5">
            Explicit Refusal & Evidence Gating
          </div>
        </div>
      </div>

      {/* Quick Access Panels */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
        {/* Recent Ingested Documents */}
        <div 
          className="rounded-2xl p-5 border shadow-sm space-y-4"
          style={{
            backgroundColor: 'var(--bg-surface)',
            borderColor: 'var(--border-color)',
          }}
        >
          <div 
            className="flex items-center justify-between border-b pb-3"
            style={{ borderColor: 'var(--border-color)' }}
          >
            <h3 className="text-xs sm:text-sm font-bold text-[var(--text-primary)] flex items-center gap-2">
              <FileText className="w-4 h-4 text-[var(--brand-accent)]" />
              <span>{t('overview.recent_activity')}</span>
            </h3>
            <button
              onClick={() => onNavigate('documents')}
              className="text-xs font-semibold flex items-center gap-1 cursor-pointer transition-colors"
              style={{ color: 'var(--brand-accent)' }}
            >
              <span>{t('overview.view_all_docs')}</span>
              <ArrowRight className="w-3.5 h-3.5" />
            </button>
          </div>

          <div className="space-y-2">
            {documents.length === 0 ? (
              <p className="text-xs text-[var(--text-muted)] py-4 text-center">
                {t('common.no_docs')}
              </p>
            ) : (
              documents.slice(0, 4).map((doc) => (
                <div
                  key={doc.id}
                  onClick={() => onNavigate('documents')}
                  className="p-3 rounded-xl border flex items-center justify-between cursor-pointer transition-all duration-150"
                  style={{
                    backgroundColor: 'var(--bg-surface-soft)',
                    borderColor: 'var(--border-color)',
                  }}
                >
                  <div className="min-w-0 pr-3">
                    <div className="text-xs font-semibold text-[var(--text-primary)] truncate">
                      {doc.title}
                    </div>
                    <div className="text-[11px] text-[var(--text-muted)] mt-0.5">
                      Authority Rank: {doc.authority_level} • Status: {doc.status}
                    </div>
                  </div>
                  <span className="text-xs font-mono text-[var(--brand-accent)] font-semibold shrink-0">
                    {doc.page_count} pg
                  </span>
                </div>
              ))
            )}
          </div>
        </div>

        {/* Governance Architecture Preview */}
        <div 
          className="rounded-2xl p-5 border shadow-sm space-y-4"
          style={{
            backgroundColor: 'var(--bg-surface)',
            borderColor: 'var(--border-color)',
          }}
        >
          <div 
            className="flex items-center justify-between border-b pb-3"
            style={{ borderColor: 'var(--border-color)' }}
          >
            <h3 className="text-xs sm:text-sm font-bold text-[var(--text-primary)] flex items-center gap-2">
              <Layers className="w-4 h-4 text-[var(--brand-accent)]" />
              <span>{t('overview.pipeline_status')}</span>
            </h3>
            <span className="text-[11px] text-[var(--success)] font-mono font-bold">100% OPERATIONAL</span>
          </div>

          <div className="space-y-2 text-xs">
            <div 
              className="p-2.5 rounded-xl border flex justify-between items-center"
              style={{ backgroundColor: 'var(--bg-surface-soft)', borderColor: 'var(--border-color)' }}
            >
              <span className="text-[var(--text-secondary)] font-medium">L7 Permission Layer (Multi-Tenant RBAC)</span>
              <span className="text-[var(--success)] font-semibold">Active</span>
            </div>
            <div 
              className="p-2.5 rounded-xl border flex justify-between items-center"
              style={{ backgroundColor: 'var(--bg-surface-soft)', borderColor: 'var(--border-color)' }}
            >
              <span className="text-[var(--text-secondary)] font-medium">L6 Authority Ladder (Config Ranks 1 to 7)</span>
              <span className="text-[var(--success)] font-semibold">Active</span>
            </div>
            <div 
              className="p-2.5 rounded-xl border flex justify-between items-center"
              style={{ backgroundColor: 'var(--bg-surface-soft)', borderColor: 'var(--border-color)' }}
            >
              <span className="text-[var(--text-secondary)] font-medium">L3 Evidence Sufficiency (Deficit Checking)</span>
              <span className="text-[var(--success)] font-semibold">Active</span>
            </div>
            <div 
              className="p-2.5 rounded-xl border flex justify-between items-center"
              style={{ backgroundColor: 'var(--bg-surface-soft)', borderColor: 'var(--border-color)' }}
            >
              <span className="text-[var(--text-secondary)] font-medium">L2 Answer-State Machine (9 States + Directives)</span>
              <span className="text-[var(--success)] font-semibold">Active</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};
