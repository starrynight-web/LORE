'use client';

import React from 'react';
import { 
  FileText, 
  Cpu, 
  Search, 
  AlertTriangle, 
  ShieldCheck, 
  Layers,
  Sparkles,
  Scan,
  Building2,
  Zap,
  Server,
  Shield,
  Mail,
  Network,
  Globe,
  ChevronRight,
  LucideIcon
} from 'lucide-react';
import { motion } from 'motion/react';
import { Organization, Workspace } from '@/lib/api';
import { useI18n } from '@/lib/i18n';

interface NavItemDef {
  id: string;
  label: string;
  icon: LucideIcon;
  tileHue: string;
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

  // Exactly SIX Tile Hues reused across groups
  const TILE = {
    blue: '#007AFF',
    indigo: '#5E5CE6',
    purple: '#AF52DE',
    green: '#34C759',
    orange: '#FF9500',
    gray: '#8E8E93',
  };

  const navGroups: NavGroupDef[] = [
    {
      title: 'WORKSPACE',
      items: [
        { id: 'overview', label: t('nav.workspace_overview') || 'Overview', icon: Layers, tileHue: TILE.blue },
        { id: 'rag', label: t('nav.governed_rag') || 'Governed Search & RAG', icon: Search, tileHue: TILE.blue },
      ]
    },
    {
      title: 'KNOWLEDGE',
      items: [
        { id: 'knowledge_grid', label: 'Knowledge Grid & RAPTOR v2.0', icon: Network, tileHue: TILE.purple, badge: 'v2.0' },
        { id: 'documents', label: t('nav.all_documents') || 'All Documents', icon: FileText, tileHue: TILE.indigo },
        { id: 'ocr', label: t('nav.live_ocr') || 'Live OCR Studio (Live)', icon: Scan, tileHue: TILE.green, badge: 'Live' },
      ]
    },
    {
      title: 'SOURCES',
      items: [
        { id: 'connectors', label: 'Enterprise Connectors (5)', icon: Globe, tileHue: TILE.orange, badge: '5' },
        { id: 'email_connect', label: 'Email Connectors (Gmail)', icon: Mail, tileHue: TILE.orange, badge: 'Gmail' },
        { id: 'activity', label: t('nav.ingestion_activity') || 'Ingestion Activity', icon: Cpu, tileHue: TILE.gray, badge: activeJobsCount > 0 ? activeJobsCount : undefined },
      ]
    },
    {
      title: 'GOVERNANCE',
      items: [
        { id: 'governance_layers', label: '9 Governance Layers 9/9', icon: Shield, tileHue: TILE.purple, badge: '9/9' },
        { id: 'review', label: t('nav.review_queue') || 'Review Queue', icon: AlertTriangle, tileHue: TILE.orange, badge: reviewCount > 0 ? reviewCount : undefined, isWarning: true },
        { id: 'audit', label: t('nav.audit_ledger') || 'Audit Ledger', icon: ShieldCheck, tileHue: TILE.gray },
      ]
    },
    {
      title: 'PLATFORM',
      items: [
        { id: 'api_connect', label: 'AI Connect (Groq)', icon: Zap, tileHue: TILE.blue, badge: 'Groq' },
        { id: 'mcp_server', label: 'MCP Server Hub', icon: Server, tileHue: TILE.indigo, badge: 'Active' },
        { id: 'settings', label: t('nav.settings') || 'Organization Settings', icon: Building2, tileHue: TILE.gray },
      ]
    }
  ];

  const orgName = currentOrg?.name || currentWorkspace?.organization_name || 'Northstar Enterprise';
  const wsName = currentWorkspace?.name || 'Default Workspace';
  const roleName = currentWorkspace?.role || currentOrg?.role || 'admin';

  return (
    <aside 
      className="w-[264px] min-w-[264px] max-w-[264px] flex flex-col h-screen select-none border-r z-20 shrink-0 transition-colors duration-200"
      style={{
        background: 'var(--sidebar-gradient)',
        borderColor: 'var(--hairline)',
      }}
    >
      {/* 1 · TENANT CARD (Sonoma's Apple-Account-card analog) */}
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
              className="w-8 h-8 rounded-lg bg-[#007AFF] text-white flex items-center justify-center font-bold text-xs shrink-0 shadow-xs"
            >
              {orgName.charAt(0).toUpperCase()}
            </div>
            <div className="min-w-0 pr-1">
              <div className="flex items-center gap-1.5">
                <span className="text-[13px] font-bold text-[var(--text-primary)] truncate leading-tight">
                  {orgName}
                </span>
              </div>
              <div className="text-[12px] text-[#6E6E73] truncate leading-tight mt-0.5">
                {wsName}
              </div>
              <div className="flex items-center gap-1 mt-1">
                <span className="text-[9px] font-semibold uppercase px-1 py-0.2 rounded bg-black/5 dark:bg-white/10 text-[var(--text-primary)]">
                  {roleName}
                </span>
                <span className="text-[9px] font-bold tracking-wider px-1 py-0.2 rounded bg-[#007AFF]/12 text-[#007AFF]">
                  ENTERPRISE
                </span>
              </div>
            </div>
          </div>
          <ChevronRight className="w-3.5 h-3.5 text-[#86868B] shrink-0" />
        </button>
      </div>

      {/* 2 · SEARCH 28px (Opens ⌘K palette) */}
      <div className="px-3 pb-3 shrink-0">
        <button
          onClick={onOpenCommandPalette}
          className="w-full h-7 px-2.5 rounded-lg border flex items-center justify-between text-xs text-[#6E6E73] cursor-pointer transition-colors hover:bg-white/70 dark:hover:bg-white/20"
          style={{
            backgroundColor: 'rgba(255, 255, 255, 0.55)',
            borderColor: 'rgba(255, 255, 255, 0.70)',
          }}
        >
          <div className="flex items-center gap-2">
            <Search className="w-3.5 h-3.5 text-[#86868B]" />
            <span className="text-[12px]">Search & Commands...</span>
          </div>
          <kbd className="px-1.5 py-0.5 text-[10px] font-mono rounded bg-white/60 dark:bg-white/20 border border-black/5 text-[#86868B]">
            ⌘K
          </kbd>
        </button>
      </div>

      {/* 3 · FIVE NAVIGATION GROUPS (20px group gaps, 30px rows, 24px solid tiles) */}
      <nav className="flex-1 px-3 overflow-y-auto space-y-5 py-1">
        {navGroups.map((group) => (
          <div key={group.title} className="space-y-0.5">
            {/* Overline Label at 55% opacity */}
            <div className="px-2 pb-1.5 text-[11px] font-semibold tracking-wider uppercase text-[#86868B]/70 select-none">
              {group.title}
            </div>

            {group.items.map((item) => {
              const Icon = item.icon;
              const isActive = activeTab === item.id;

              return (
                <button
                  key={item.id}
                  onClick={() => {
                    setActiveTab(item.id);
                    if (typeof window !== 'undefined' && window.innerWidth < 768 && onClose) {
                      onClose();
                    }
                  }}
                  className="w-full h-[30px] relative flex items-center justify-between px-2 rounded-lg text-left cursor-pointer transition-colors select-none"
                  style={{
                    color: isActive ? 'var(--text-primary)' : 'var(--text-secondary)'
                  }}
                >
                  {/* Active sliding pill via shared layoutId */}
                  {isActive && (
                    <motion.div
                      layoutId="sidebar-active-pill"
                      className="absolute inset-0 rounded-lg shadow-xs pointer-events-none"
                      style={{
                        backgroundColor: 'rgba(255, 255, 255, 0.75)',
                        border: '1px solid rgba(255, 255, 255, 0.90)',
                      }}
                      transition={{ type: 'spring', stiffness: 400, damping: 32 }}
                    />
                  )}

                  {/* Row content */}
                  <div className="relative z-10 flex items-center gap-2 min-w-0 pr-1">
                    {/* 24px Solid Tile (14px white Lucide glyph) */}
                    <div 
                      className="w-6 h-6 rounded-md flex items-center justify-center shrink-0 shadow-2xs"
                      style={{ backgroundColor: item.tileHue }}
                    >
                      <Icon className="w-3.5 h-3.5 text-white stroke-[2.2]" />
                    </div>
                    {/* 13/500 label */}
                    <span 
                      className="text-[13px] truncate"
                      style={{ fontWeight: isActive ? 600 : 500 }}
                    >
                      {item.label}
                    </span>
                  </div>

                  {/* 10px mono badge */}
                  {item.badge !== undefined && (
                    <span 
                      className="relative z-10 text-[10px] font-mono font-medium px-1.5 py-0.2 rounded-md shrink-0 tabular-nums"
                      style={{
                        backgroundColor: item.isWarning 
                          ? 'var(--orange-tint)' 
                          : 'rgba(0, 0, 0, 0.06)',
                        color: item.isWarning 
                          ? 'var(--orange-text)' 
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

      {/* 4 · FOOTER: "Anti-Hallucination Active · 9/9 layers" Translucent Card */}
      <div className="p-3 shrink-0">
        <div 
          className="p-2.5 rounded-xl border transition-colors select-none"
          style={{
            backgroundColor: 'rgba(255, 255, 255, 0.55)',
            borderColor: 'rgba(255, 255, 255, 0.70)',
          }}
        >
          <div className="flex items-center gap-1.5 text-[11px] font-semibold text-[#007AFF] mb-0.5">
            <Sparkles className="w-3 h-3" />
            <span>Anti-Hallucination Active</span>
          </div>
          <p className="text-[10px] text-[#6E6E73] leading-tight">
            9/9 layers operational · Fail-closed evidence gate.
          </p>
        </div>
      </div>
    </aside>
  );
};
