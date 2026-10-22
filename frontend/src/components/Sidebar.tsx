'use client';

import React from 'react';
import { 
  FolderKanban, 
  FileText, 
  Cpu, 
  Search, 
  AlertTriangle, 
  ShieldCheck, 
  Clock, 
  Layers,
  Sparkles,
  Scan,
  Building2
} from 'lucide-react';

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
  const navItems = [
    { id: 'overview', label: 'Workspace Overview', icon: Layers },
    { id: 'ocr', label: 'Live OCR Studio', icon: Scan, badge: 'Realtime', badgeColor: 'bg-emerald-600' },
    { id: 'documents', label: 'All Documents', icon: FileText },
    { id: 'activity', label: 'Ingestion Activity', icon: Cpu, badge: activeJobsCount > 0 ? activeJobsCount : undefined, badgeColor: 'bg-blue-600' },
    { id: 'rag', label: 'Governed Search & RAG', icon: Search, highlight: true },
    { id: 'review', label: 'Review Queue', icon: AlertTriangle, badge: reviewCount > 0 ? reviewCount : undefined, badgeColor: 'bg-amber-600' },
    { id: 'audit', label: 'Audit Ledger', icon: ShieldCheck },
    { id: 'settings', label: 'Organization & SaaS', icon: Building2 },
  ];

  return (
    <aside className="w-64 bg-slate-900 border-r border-slate-800 flex flex-col h-screen text-slate-300 select-none">
      {/* Brand Header */}
      <div className="h-16 flex items-center px-6 border-b border-slate-800 gap-3">
        <div className="w-9 h-9 rounded-lg bg-gradient-to-tr from-indigo-600 to-violet-500 flex items-center justify-center text-white shadow-lg shadow-indigo-500/20">
          <FolderKanban className="w-5 h-5" />
        </div>
        <div>
          <div className="flex items-center gap-2">
            <span className="font-bold text-white tracking-wide text-base">LORE</span>
            <span className="text-[10px] font-semibold uppercase tracking-wider px-1.5 py-0.5 rounded bg-indigo-500/20 text-indigo-400 border border-indigo-500/30">
              Enterprise
            </span>
          </div>
          <p className="text-[11px] text-slate-400">Governed Knowledge Grid</p>
        </div>
      </div>

      {/* Navigation */}
      <nav className="flex-1 px-3 py-4 space-y-1 overflow-y-auto">
        <div className="px-3 pb-2 text-[11px] font-semibold uppercase tracking-wider text-slate-400">
          Knowledge Workspace
        </div>
        {navItems.map((item) => {
          const Icon = item.icon;
          const isActive = activeTab === item.id;
          return (
            <button
              key={item.id}
              onClick={() => setActiveTab(item.id)}
              className={`w-full flex items-center justify-between px-3 py-2.5 rounded-lg text-sm font-medium transition-all ${
                isActive
                  ? 'bg-indigo-600 text-white shadow-md shadow-indigo-600/30'
                  : 'text-slate-300 hover:bg-slate-800/80 hover:text-white'
              }`}
            >
              <div className="flex items-center gap-3">
                <Icon className={`w-4 h-4 ${isActive ? 'text-white' : item.highlight ? 'text-indigo-400' : 'text-slate-400'}`} />
                <span>{item.label}</span>
              </div>
              {item.badge !== undefined && (
                <span className={`text-[11px] font-bold px-2 py-0.5 rounded-full text-white ${item.badgeColor}`}>
                  {item.badge}
                </span>
              )}
            </button>
          );
        })}
      </nav>

      {/* Governance Banner */}
      <div className="p-4 border-t border-slate-800">
        <div className="p-3 rounded-lg bg-slate-800/60 border border-slate-700/50 text-xs">
          <div className="flex items-center gap-2 text-indigo-400 font-semibold mb-1">
            <Sparkles className="w-3.5 h-3.5" />
            <span>Anti-Hallucination Active</span>
          </div>
          <p className="text-slate-400 text-[11px] leading-relaxed">
            Deterministic 9-state governance gate with source authority enforcement.
          </p>
        </div>
      </div>
    </aside>
  );
};
