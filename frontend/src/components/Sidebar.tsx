'use client';

import React from 'react';
import { 
  FileText, 
  Cpu, 
  Search, 
  AlertTriangle, 
  ShieldCheck, 
  Layers, 
  Scan, 
  Building2, 
  Zap, 
  Server, 
  Shield, 
  Mail, 
  Network, 
  Globe, 
  ChevronRight, 
  Copy, 
  Sun, 
  Moon, 
  LucideIcon 
} from 'lucide-react';
import { motion } from 'motion/react';
import { Organization, Workspace } from '@/lib/api';
import { useI18n } from '@/lib/i18n';
import { useTheme } from '@/lib/theme';

type WellTone = 'sky' | 'lavender' | 'sage' | 'peach' | 'amber' | 'muted';

interface NavItemDef {
  id: string;
  label: string;
  icon: LucideIcon;
  tone: WellTone;
  badge?: string | number;
  isWarning?: boolean;
}

interface NavGroupDef {
  title: string;
  items: NavItemDef[];
}

interface SidebarProps {
  activeTab: string;
  setActiveTab: (tab: string) => void;
  reviewCount?: number;
  activeJobsCount?: number;
  isOpen?: boolean;
  onClose?: () => void;
  currentOrg?: Organization | null;
  currentWorkspace?: Workspace | null;
  workspaces?: Workspace[];
  onSelectWorkspace?: (ws: Workspace) => void;
  onOpenCommandPalette?: () => void;
  onOpenWorkspaceSwitcher?: () => void;
}

const WELL_STYLES: Record<WellTone, { bg: string; fg: string }> = {
  sky: { bg: 'var(--well-sky-bg)', fg: 'var(--well-sky-fg)' },
  lavender: { bg: 'var(--well-lavender-bg)', fg: 'var(--well-lavender-fg)' },
  sage: { bg: 'var(--well-sage-bg)', fg: 'var(--well-sage-fg)' },
  peach: { bg: 'var(--well-peach-bg)', fg: 'var(--well-peach-fg)' },
  amber: { bg: 'var(--well-amber-bg)', fg: 'var(--well-amber-fg)' },
  muted: { bg: 'var(--well-muted-bg)', fg: 'var(--well-muted-fg)' },
};

export const Sidebar: React.FC<SidebarProps> = ({
  activeTab,
  setActiveTab,
  reviewCount = 0,
  activeJobsCount = 0,
  isOpen = true,
  onClose,
  currentOrg,
  currentWorkspace,
  workspaces = [],
  onSelectWorkspace,
  onOpenCommandPalette,
  onOpenWorkspaceSwitcher
}) => {
  const { t } = useI18n();
  const { theme, setTheme } = useTheme();

  const navGroups: NavGroupDef[] = [
    {
      title: 'WORKSPACE',
      items: [
        { id: 'overview', label: t('nav.workspace_overview') || 'Overview', icon: Layers, tone: 'sky' },
        { id: 'rag', label: t('nav.governed_rag') || 'Governed Search & RAG', icon: Search, tone: 'sky' },
      ]
    },
    {
      title: 'KNOWLEDGE',
      items: [
        { id: 'knowledge_grid', label: 'Knowledge Grid & RAPTOR v2.0', icon: Network, tone: 'lavender', badge: 'v2.0' },
        { id: 'documents', label: t('nav.all_documents') || 'All Documents', icon: FileText, tone: 'lavender' },
        { id: 'ocr', label: t('nav.live_ocr') || 'Live OCR Studio (Live)', icon: Scan, tone: 'sage', badge: 'Live' },
      ]
    },
    {
      title: 'SOURCES',
      items: [
        { id: 'connectors', label: 'Enterprise Connectors (5)', icon: Globe, tone: 'peach', badge: '5' },
        { id: 'email_connect', label: 'Email Connectors (Gmail)', icon: Mail, tone: 'peach', badge: 'Gmail' },
        { id: 'activity', label: t('nav.ingestion_activity') || 'Ingestion Activity', icon: Cpu, tone: 'muted', badge: activeJobsCount > 0 ? activeJobsCount : undefined },
      ]
    },
    {
      title: 'GOVERNANCE',
      items: [
        { id: 'governance_layers', label: '9 Governance Layers 9/9', icon: Shield, tone: 'lavender', badge: '9/9' },
        { id: 'review', label: t('nav.review_queue') || 'Review Queue', icon: AlertTriangle, tone: 'amber', badge: reviewCount > 0 ? reviewCount : undefined, isWarning: true },
        { id: 'audit', label: t('nav.audit_ledger') || 'Audit Ledger', icon: ShieldCheck, tone: 'muted' },
      ]
    },
    {
      title: 'PLATFORM',
      items: [
        { id: 'api_connect', label: 'AI Connect (Groq)', icon: Zap, tone: 'sky', badge: 'Groq' },
        { id: 'mcp_server', label: 'MCP Server Hub', icon: Server, tone: 'lavender', badge: 'Active' },
        { id: 'settings', label: t('nav.settings') || 'Organization Settings', icon: Building2, tone: 'muted' },
      ]
    }
  ];

  const orgName = currentOrg?.name || currentWorkspace?.organization_name || 'Northstar Enterprise';
  const wsName = currentWorkspace?.name || 'Default Workspace';
  const roleName = currentWorkspace?.role || currentOrg?.role || 'admin';

  return (
    <aside 
      className="w-[268px] min-w-[268px] max-w-[268px] flex flex-col h-screen sticky top-0 select-none border-r z-20 shrink-0 transition-colors duration-200"
      style={{
        background: 'var(--sidebar-gradient)',
        borderColor: 'var(--hairline)',
      }}
    >
      {/* 1 · TENANT CARD */}
      <div className="p-3 pb-2 shrink-0">
        <button
          onClick={onOpenWorkspaceSwitcher}
          className="w-full text-left p-2.5 rounded-xl border flex items-center justify-between cursor-pointer transition-all hover:bg-white/40 dark:hover:bg-white/10 active:scale-[0.98]"
          style={{
            backgroundColor: 'rgba(255, 255, 255, 0.45)',
            borderColor: 'rgba(255, 255, 255, 0.60)',
          }}
          title="Click to switch workspace"
        >
          <div className="flex items-center gap-2.5 min-w-0">
            {/* Org Glyph */}
            <div 
              className="w-8 h-8 rounded-lg flex items-center justify-center font-bold text-xs shrink-0 shadow-xs"
              style={{
                backgroundColor: 'var(--lavender-deep)',
                color: '#ffffff',
              }}
            >
              {orgName.charAt(0).toUpperCase()}
            </div>
            <div className="min-w-0 pr-1">
              <div className="flex items-center gap-1.5">
                <span className="text-[13px] font-bold text-[var(--text-primary)] truncate leading-tight">
                  {orgName}
                </span>
              </div>
              <div className="text-[12px] text-[var(--text-secondary)] truncate leading-tight mt-0.5">
                {wsName}
              </div>
              <div className="flex items-center gap-1 mt-1">
                <span className="text-[9px] font-semibold uppercase px-1 py-0.2 rounded bg-black/5 dark:bg-white/10 text-[var(--text-primary)]">
                  {roleName}
                </span>
                <span 
                  className="text-[9px] font-bold tracking-wider px-1 py-0.2 rounded"
                  style={{
                    backgroundColor: 'var(--well-lavender-bg)',
                    color: 'var(--well-lavender-fg)',
                  }}
                >
                  ENTERPRISE
                </span>
              </div>
              {currentWorkspace?.id && (
                <div 
                  onClick={(e) => {
                    e.stopPropagation();
                    navigator.clipboard.writeText(currentWorkspace.id);
                  }}
                  className="flex items-center gap-1 mt-1 text-[10px] font-mono text-[var(--text-muted)] hover:text-[var(--lavender-deep)] transition-colors cursor-pointer group"
                  title={`Workspace UUID: ${currentWorkspace.id} (Click to copy)`}
                >
                  <span className="truncate">UUID: {currentWorkspace.id.slice(0, 8)}...</span>
                  <Copy className="w-2.5 h-2.5 opacity-60 group-hover:opacity-100 shrink-0" />
                </div>
              )}
            </div>
          </div>
          <ChevronRight className="w-3.5 h-3.5 text-[var(--text-muted)] shrink-0" />
        </button>
      </div>

      {/* 2 · SEARCH 28px (Opens ⌘K palette) */}
      <div className="px-3 pb-3 shrink-0">
        <button
          onClick={onOpenCommandPalette}
          className="w-full h-8 px-2.5 rounded-lg border flex items-center justify-between text-xs text-[var(--text-secondary)] cursor-pointer transition-colors hover:bg-white/70 dark:hover:bg-white/20"
          style={{
            backgroundColor: 'rgba(255, 255, 255, 0.55)',
            borderColor: 'rgba(255, 255, 255, 0.70)',
          }}
        >
          <div className="flex items-center gap-2">
            <Search className="w-3.5 h-3.5 text-[var(--text-muted)]" />
            <span className="text-[12px]">Search & Commands...</span>
          </div>
          <kbd className="px-1.5 py-0.5 text-[10px] font-mono rounded bg-white/60 dark:bg-white/20 border border-black/5 dark:border-white/10 text-[var(--text-muted)]">
            ⌘K
          </kbd>
        </button>
      </div>

      {/* 3 · FIVE NAVIGATION GROUPS */}
      <nav className="flex-1 px-3 overflow-y-auto space-y-4 py-1" aria-label="Main Navigation">
        {navGroups.map((group) => (
          <div key={group.title} className="space-y-0.5">
            {/* Overline Label */}
            <div className="px-2 pb-1 text-[10px] font-bold tracking-wider uppercase text-[var(--text-muted)] select-none">
              {group.title}
            </div>

            {group.items.map((item) => {
              const Icon = item.icon;
              const isActive = activeTab === item.id;
              const wellStyle = WELL_STYLES[item.tone] || WELL_STYLES.muted;

              return (
                <button
                  key={item.id}
                  onClick={() => {
                    setActiveTab(item.id);
                    if (typeof window !== 'undefined' && window.innerWidth < 768 && onClose) {
                      onClose();
                    }
                  }}
                  aria-current={isActive ? 'page' : undefined}
                  className="w-full h-10 min-h-[40px] relative flex items-center justify-between px-2.5 rounded-xl text-left cursor-pointer transition-colors select-none"
                  style={{
                    color: isActive ? '#ffffff' : 'var(--text-secondary)',
                  }}
                >
                  {/* Active sliding pill */}
                  {isActive && (
                    <motion.div
                      layoutId="sidebar-active-pill"
                      className="absolute inset-0 rounded-xl pointer-events-none"
                      style={{
                        backgroundColor: 'var(--lavender-active)',
                      }}
                      transition={{ duration: 0.14, ease: 'easeOut' }}
                    />
                  )}

                  {/* Row content */}
                  <div className="relative z-10 flex items-center gap-2.5 min-w-0 pr-1">
                    {/* Icon Well: 28px rounded square */}
                    <div 
                      className="w-7 h-7 rounded-lg flex items-center justify-center shrink-0 transition-colors"
                      aria-hidden="true"
                      style={{
                        backgroundColor: isActive ? 'rgba(255, 255, 255, 0.20)' : wellStyle.bg,
                        color: isActive ? '#ffffff' : wellStyle.fg,
                      }}
                    >
                      <Icon className="w-3.5 h-3.5 stroke-[2]" />
                    </div>
                    {/* Label */}
                    <span 
                      className="text-[12.5px] truncate"
                      style={{ 
                        fontWeight: isActive ? 600 : 500,
                        color: isActive ? '#ffffff' : undefined
                      }}
                    >
                      {item.label}
                    </span>
                  </div>

                  {/* Mono Badge */}
                  {item.badge !== undefined && (
                    <span 
                      className="relative z-10 text-[10px] font-mono font-medium px-1.5 py-0.5 rounded-md shrink-0 tabular-nums"
                      style={{
                        backgroundColor: isActive 
                          ? 'rgba(255, 255, 255, 0.20)' 
                          : item.isWarning 
                            ? 'var(--well-amber-bg)'
                            : item.badge === 'Live'
                              ? 'var(--well-sage-bg)'
                              : (item.badge === 'Active' || item.badge === '9/9' || item.badge === 'v2.0')
                                ? 'var(--well-lavender-bg)'
                                : 'rgba(0, 0, 0, 0.06)',
                        color: isActive 
                          ? '#ffffff' 
                          : item.isWarning 
                            ? 'var(--well-amber-fg)'
                            : item.badge === 'Live'
                              ? 'var(--well-sage-fg)'
                              : (item.badge === 'Active' || item.badge === '9/9' || item.badge === 'v2.0')
                                ? 'var(--well-lavender-fg)'
                                : 'var(--text-secondary)',
                      }}
                    >
                      {item.badge}
                    </span>
                  )}
                </button>
              );
            })}
          </div>
        ))}
      </nav>

      {/* 4 · FOOTER: Segmented Theme Toggle + Operational Status */}
      <div className="p-3 shrink-0 space-y-2">
        {/* Segmented Moon/Sun Theme Toggle */}
        <div 
          className="flex items-center justify-between p-1 rounded-lg border"
          style={{
            backgroundColor: 'rgba(255, 255, 255, 0.35)',
            borderColor: 'rgba(255, 255, 255, 0.50)',
          }}
        >
          <button
            type="button"
            onClick={() => setTheme('light')}
            aria-pressed={theme === 'light'}
            className="flex-1 flex items-center justify-center gap-1.5 py-1 px-2 rounded-md text-xs font-medium transition-all cursor-pointer"
            style={{
              backgroundColor: theme === 'light' ? 'var(--bg-card)' : 'transparent',
              color: theme === 'light' ? 'var(--text-primary)' : 'var(--text-muted)',
              boxShadow: theme === 'light' ? '0 1px 3px rgba(0,0,0,0.08)' : 'none',
            }}
          >
            <Sun className="w-3.5 h-3.5 text-[var(--well-amber-fg)]" />
            <span>Light</span>
          </button>
          <button
            type="button"
            onClick={() => setTheme('dark')}
            aria-pressed={theme === 'dark'}
            className="flex-1 flex items-center justify-center gap-1.5 py-1 px-2 rounded-md text-xs font-medium transition-all cursor-pointer"
            style={{
              backgroundColor: theme === 'dark' ? 'var(--bg-card)' : 'transparent',
              color: theme === 'dark' ? 'var(--text-primary)' : 'var(--text-muted)',
              boxShadow: theme === 'dark' ? '0 1px 3px rgba(0,0,0,0.25)' : 'none',
            }}
          >
            <Moon className="w-3.5 h-3.5 text-[var(--well-lavender-fg)]" />
            <span>Dark</span>
          </button>
        </div>

        {/* Operational Status Card */}
        <div 
          className="p-2.5 rounded-xl border transition-colors select-none"
          style={{
            backgroundColor: 'rgba(255, 255, 255, 0.45)',
            borderColor: 'rgba(255, 255, 255, 0.60)',
          }}
        >
          <div className="flex items-center gap-2 mb-1">
            <span className="relative flex h-2 w-2">
              <span 
                className="animate-ping absolute inline-flex h-full w-full rounded-full opacity-75"
                style={{ backgroundColor: 'var(--sage)' }}
              />
              <span 
                className="relative inline-flex rounded-full h-2 w-2"
                style={{ backgroundColor: 'var(--sage-deep)' }}
              />
            </span>
            <span className="text-[11px] font-semibold text-[var(--text-primary)]">
              All systems operational
            </span>
          </div>
          <p className="text-[10px] text-[var(--text-secondary)] leading-tight pl-4">
            Fail-closed evidence · 9/9 active.
          </p>
        </div>
      </div>
    </aside>
  );
};
