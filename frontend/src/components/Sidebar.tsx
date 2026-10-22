'use client';

import React from 'react';
import { 
  FolderKanban, 
  FileText, 
  Cpu, 
  Search, 
  AlertTriangle, 
  ShieldCheck, 
  Layers,
  Sparkles,
  Scan,
  Building2
} from 'lucide-react';
import { useI18n } from '@/lib/i18n';

interface SidebarProps {
  activeTab: string;
  setActiveTab: (tab: string) => void;
  reviewCount?: number;
  activeJobsCount?: number;
}

export const Sidebar: React.FC<SidebarProps> = ({
  activeTab,
  setActiveTab,
  reviewCount = 0,
  activeJobsCount = 0
}) => {
  const { t } = useI18n();

  const navItems = [
    { id: 'overview', label: t('nav.workspace_overview'), icon: Layers },
    { id: 'ocr', label: t('nav.live_ocr'), icon: Scan, badge: 'Live', isLive: true },
    { id: 'documents', label: t('nav.all_documents'), icon: FileText },
    { id: 'activity', label: t('nav.ingestion_activity'), icon: Cpu, badge: activeJobsCount > 0 ? activeJobsCount : undefined },
    { id: 'rag', label: t('nav.governed_rag'), icon: Search, highlight: true },
    { id: 'review', label: t('nav.review_queue'), icon: AlertTriangle, badge: reviewCount > 0 ? reviewCount : undefined, isWarning: true },
    { id: 'audit', label: t('nav.audit_ledger'), icon: ShieldCheck },
    { id: 'settings', label: t('nav.settings'), icon: Building2 },
  ];

  return (
    <aside 
      className="w-64 border-r flex flex-col h-screen select-none transition-colors duration-200 z-10"
      style={{
        backgroundColor: 'var(--bg-surface)',
        borderColor: 'var(--border-color)',
      }}
    >
      {/* Brand Header */}
      <div 
        className="h-16 flex items-center px-6 border-b gap-3"
        style={{ borderColor: 'var(--border-color)' }}
      >
        <div 
          className="w-9 h-9 rounded-xl flex items-center justify-center shadow-sm"
          style={{
            backgroundColor: 'var(--brand-accent)',
            color: 'var(--cta-text)',
          }}
        >
          <FolderKanban className="w-5 h-5" />
        </div>
        <div>
          <div className="flex items-center gap-2">
            <span className="font-bold tracking-wide text-base text-[var(--text-primary)]">
              {t('app.name')}
            </span>
            <span 
              className="text-[10px] font-bold uppercase tracking-wider px-1.5 py-0.5 rounded border"
              style={{
                backgroundColor: 'var(--accent-light)',
                borderColor: 'var(--border-color)',
                color: 'var(--brand-accent)',
              }}
            >
              Enterprise
            </span>
          </div>
          <p className="text-[11px] text-[var(--text-muted)]">{t('app.tagline')}</p>
        </div>
      </div>

      {/* Navigation Links */}
      <nav className="flex-1 px-3 py-4 space-y-1.5 overflow-y-auto">
        <div className="px-3 pb-2 text-[10px] font-bold uppercase tracking-wider text-[var(--text-muted)]">
          {t('nav.knowledge_workspace')}
        </div>
        {navItems.map((item) => {
          const Icon = item.icon;
          const isActive = activeTab === item.id;
          return (
            <button
              key={item.id}
              onClick={() => setActiveTab(item.id)}
              className="w-full flex items-center justify-between px-3 py-2 rounded-xl text-xs font-semibold transition-all duration-150 cursor-pointer text-left"
              style={{
                backgroundColor: isActive ? 'var(--accent-light)' : 'transparent',
                color: isActive ? 'var(--brand-accent)' : 'var(--text-secondary)',
                border: isActive ? '1px solid var(--border-color)' : '1px solid transparent',
              }}
            >
              <div className="flex items-center gap-2.5">
                <Icon 
                  className="w-4 h-4 transition-colors" 
                  style={{
                    color: isActive ? 'var(--brand-accent)' : item.highlight ? 'var(--accent-parrot)' : 'var(--text-muted)',
                  }}
                />
                <span className="truncate">{item.label}</span>
              </div>
              {item.badge !== undefined && (
                <span 
                  className="text-[10px] font-bold px-2 py-0.5 rounded-full"
                  style={{
                    backgroundColor: item.isWarning ? 'var(--warning-bg)' : 'var(--accent-light)',
                    color: item.isWarning ? 'var(--warning)' : 'var(--brand-accent)',
                    border: '1px solid var(--border-color)',
                  }}
                >
                  {item.badge}
                </span>
              )}
            </button>
          );
        })}
      </nav>

      {/* Anti-Hallucination Governance Footer */}
      <div 
        className="p-4 border-t"
        style={{ borderColor: 'var(--border-color)' }}
      >
        <div 
          className="p-3 rounded-xl border"
          style={{
            backgroundColor: 'var(--bg-surface-soft)',
            borderColor: 'var(--border-color)',
          }}
        >
          <div className="flex items-center gap-1.5 text-xs font-bold text-[var(--brand-accent)] mb-1">
            <Sparkles className="w-3.5 h-3.5" />
            <span>{t('nav.anti_hallucination')}</span>
          </div>
          <p className="text-[11px] text-[var(--text-muted)] leading-relaxed">
            {t('nav.anti_hallucination_desc')}
          </p>
        </div>
      </div>
    </aside>
  );
};
