'use client';

import React, { useState } from 'react';
import { 
  ShieldCheck, 
  Sparkles, 
  FileText, 
  Activity, 
  Users, 
  Search, 
  Download, 
  Share2, 
  Lock, 
  Unlock, 
  Settings, 
  Printer, 
  Check, 
  ExternalLink,
  ChevronDown,
  Sun,
  Moon
} from 'lucide-react';
import { DocsConfig, api } from '@/lib/api';
import { useTheme } from '@/lib/theme';

export type DocsMode = 'pitch_deck' | 'whitepaper' | 'live_ops' | 'team';

interface DocsHeaderProps {
  mode: DocsMode;
  onModeChange: (mode: DocsMode) => void;
  searchQuery: string;
  onSearchChange: (q: string) => void;
  config?: DocsConfig;
  isAdmin: boolean;
  onOpenAdmin: () => void;
}

export const DocsHeader: React.FC<DocsHeaderProps> = ({
  mode,
  onModeChange,
  searchQuery,
  onSearchChange,
  config,
  isAdmin,
  onOpenAdmin
}) => {
  const { theme, toggleTheme } = useTheme();
  const isDark = theme === 'dark';
  const [showExportMenu, setShowExportMenu] = useState(false);
  const [copied, setCopied] = useState(false);

  const handleCopyLink = () => {
    if (typeof window !== 'undefined') {
      const url = `${window.location.origin}/docs?mode=${mode}`;
      navigator.clipboard.writeText(url);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
      setShowExportMenu(false);
    }
  };

  const handlePrint = () => {
    setShowExportMenu(false);
    window.print();
  };

  return (
    <header className="sticky top-0 z-40 w-full backdrop-blur-md border-b transition-all duration-200 bg-white/85 dark:bg-slate-900/85 border-slate-200/80 dark:border-slate-800 shadow-xs"
    >
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex items-center justify-between h-16 gap-4">
          
          {/* Logo & Platform Name */}
          <div className="flex items-center gap-3 shrink-0">
            <a href="/" className="flex items-center gap-2 group">
              <div className="w-9 h-9 rounded-xl flex items-center justify-center font-bold text-base shadow-lg transition-transform group-hover:scale-105"
                style={{
                  background: 'linear-gradient(135deg, #0284c7 0%, #2563eb 100%)',
                  color: '#ffffff',
                }}
              >
                <ShieldCheck className="w-5 h-5 text-white" />
              </div>
              <div className="hidden sm:block">
                <div className="flex items-center gap-1.5">
                  <span className="font-extrabold text-sm tracking-tight text-slate-900 dark:text-white">
                    LORE
                  </span>
                  <span className="px-1.5 py-0.5 rounded text-[10px] font-bold tracking-wide uppercase bg-blue-50 dark:bg-sky-500/15 text-blue-600 dark:text-sky-400 border border-blue-200 dark:border-sky-500/30">
                    /docs
                  </span>
                </div>
                <p className="text-[10px] text-slate-500 dark:text-slate-400 font-mono leading-none mt-0.5">
                  v2.0.0-enterprise
                </p>
              </div>
            </a>

            {/* Publishing Status Badge */}
            {config && (
              <div className="hidden md:flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px] font-medium border"
                style={{
                  backgroundColor: config.admin_override
                    ? 'rgba(16, 185, 129, 0.12)'
                    : config.is_currently_open
                    ? 'rgba(16, 185, 129, 0.12)'
                    : 'rgba(245, 158, 11, 0.12)',
                  borderColor: config.admin_override
                    ? 'rgba(16, 185, 129, 0.3)'
                    : config.is_currently_open
                    ? 'rgba(16, 185, 129, 0.3)'
                    : 'rgba(245, 158, 11, 0.3)',
                  color: config.admin_override
                    ? '#059669'
                    : config.is_currently_open
                    ? '#059669'
                    : '#d97706'
                }}
                title={config.admin_override ? 'Admin Override Active' : `Schedule Window: June 10 - June 14`}
              >
                <span className="w-2 h-2 rounded-full animate-pulse"
                  style={{ backgroundColor: config.is_currently_open ? '#10b981' : '#f59e0b' }}
                />
                <span>
                  {config.admin_override 
                    ? 'Preview Active (Override)' 
                    : config.is_currently_open 
                    ? 'Showcase Live (June 10-14)' 
                    : 'Restricted Showcase'}
                </span>
              </div>
            )}
          </div>

          {/* Mode Switcher Tabs */}
          <nav className="flex items-center gap-1 p-1 rounded-xl border bg-slate-100/90 dark:bg-slate-900/60 border-slate-200/80 dark:border-slate-800 overflow-x-auto shadow-inner"
          >
            <button
              onClick={() => onModeChange('pitch_deck')}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold transition-all ${
                mode === 'pitch_deck'
                  ? 'bg-blue-600 text-white shadow-md shadow-blue-500/20'
                  : 'text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white hover:bg-white dark:hover:bg-slate-800/50'
              }`}
            >
              <Sparkles className="w-3.5 h-3.5" />
              <span>Pitch Deck</span>
            </button>

            <button
              onClick={() => onModeChange('whitepaper')}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold transition-all ${
                mode === 'whitepaper'
                  ? 'bg-blue-600 text-white shadow-md shadow-blue-500/20'
                  : 'text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white hover:bg-white dark:hover:bg-slate-800/50'
              }`}
            >
              <FileText className="w-3.5 h-3.5" />
              <span>Technical Whitepaper</span>
            </button>

            <button
              onClick={() => onModeChange('live_ops')}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold transition-all ${
                mode === 'live_ops'
                  ? 'bg-blue-600 text-white shadow-md shadow-blue-500/20'
                  : 'text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white hover:bg-white dark:hover:bg-slate-800/50'
              }`}
            >
              <Activity className="w-3.5 h-3.5" />
              <span>Live Ops</span>
            </button>

            <button
              onClick={() => onModeChange('team')}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold transition-all ${
                mode === 'team'
                  ? 'bg-blue-600 text-white shadow-md shadow-blue-500/20'
                  : 'text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white hover:bg-white dark:hover:bg-slate-800/50'
              }`}
            >
              <Users className="w-3.5 h-3.5" />
              <span>Team</span>
            </button>
          </nav>

          {/* Right Action Bar: Search, Theme Toggle, Export, Admin Drawer */}
          <div className="flex items-center gap-2">
            
            {/* Global Search */}
            <div className="relative hidden lg:block w-48">
              <Search className="w-3.5 h-3.5 absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
              <input
                type="text"
                placeholder="Search /docs..."
                value={searchQuery}
                onChange={(e) => onSearchChange(e.target.value)}
                className="w-full pl-8 pr-3 py-1.5 text-xs rounded-xl border bg-white dark:bg-slate-900/60 border-slate-200 dark:border-slate-800 focus:outline-none focus:border-blue-500 text-slate-900 dark:text-white placeholder-slate-400 transition-colors shadow-xs"
              />
              {searchQuery && (
                <button
                  onClick={() => onSearchChange('')}
                  className="absolute right-2.5 top-1/2 -translate-y-1/2 text-xs text-slate-400 hover:text-slate-700 dark:hover:text-white"
                >
                  ×
                </button>
              )}
            </div>

            {/* Light / Dark Theme Toggle Button */}
            <button
              onClick={toggleTheme}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl border text-xs font-semibold transition-all cursor-pointer bg-white dark:bg-slate-800/70 border-slate-200 dark:border-slate-700 text-slate-700 dark:text-slate-200 hover:border-blue-500 shadow-xs"
              title={isDark ? "Switch to Light mode" : "Switch to Dark mode"}
              aria-label="Toggle theme"
            >
              {isDark ? (
                <>
                  <Sun className="w-3.5 h-3.5 text-amber-400" />
                  <span className="hidden sm:inline">Light</span>
                </>
              ) : (
                <>
                  <Moon className="w-3.5 h-3.5 text-blue-600" />
                  <span className="hidden sm:inline">Dark</span>
                </>
              )}
            </button>

            {/* Export Dropdown */}
            <div className="relative">
              <button
                onClick={() => setShowExportMenu(!showExportMenu)}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl border text-xs font-semibold transition-all cursor-pointer bg-white dark:bg-slate-800/70 border-slate-200 dark:border-slate-700 text-slate-700 dark:text-slate-200 hover:border-blue-500 shadow-xs"
              >
                <Download className="w-3.5 h-3.5 text-blue-500" />
                <span className="hidden sm:inline">Export</span>
                <ChevronDown className="w-3 h-3 text-slate-400" />
              </button>

              {showExportMenu && (
                <div 
                  className="absolute right-0 mt-2 w-56 rounded-xl border shadow-2xl p-1.5 z-50 animate-in fade-in zoom-in-95 backdrop-blur-md bg-white dark:bg-slate-900 border-slate-200 dark:border-slate-800 text-slate-800 dark:text-slate-200"
                >
                  <button
                    onClick={handlePrint}
                    className="w-full flex items-center gap-2.5 px-3 py-2 rounded-lg text-xs font-medium text-left hover:bg-slate-100 dark:hover:bg-slate-800 text-slate-800 dark:text-slate-200 transition-colors cursor-pointer"
                  >
                    <Printer className="w-4 h-4 text-emerald-500" />
                    <div>
                      <div className="font-semibold">Print / Save as PDF</div>
                      <div className="text-[10px] text-slate-500 dark:text-slate-400">Clean, print-ready document</div>
                    </div>
                  </button>

                  <a
                    href={api.getDocsExportUrl('markdown')}
                    download
                    onClick={() => setShowExportMenu(false)}
                    className="w-full flex items-center gap-2.5 px-3 py-2 rounded-lg text-xs font-medium text-left hover:bg-slate-100 dark:hover:bg-slate-800 text-slate-800 dark:text-slate-200 transition-colors cursor-pointer"
                  >
                    <FileText className="w-4 h-4 text-blue-500" />
                    <div>
                      <div className="font-semibold">Download Markdown (.md)</div>
                      <div className="text-[10px] text-slate-500 dark:text-slate-400">Full technical whitepaper</div>
                    </div>
                  </a>

                  <a
                    href={api.getDocsExportUrl('json')}
                    download
                    onClick={() => setShowExportMenu(false)}
                    className="w-full flex items-center gap-2.5 px-3 py-2 rounded-lg text-xs font-medium text-left hover:bg-slate-100 dark:hover:bg-slate-800 text-slate-800 dark:text-slate-200 transition-colors cursor-pointer"
                  >
                    <Download className="w-4 h-4 text-purple-500" />
                    <div>
                      <div className="font-semibold">Download JSON (.json)</div>
                      <div className="text-[10px] text-slate-500 dark:text-slate-400">Structured schema payload</div>
                    </div>
                  </a>

                  <div className="my-1 border-t border-slate-200 dark:border-slate-800" />

                  <button
                    onClick={handleCopyLink}
                    className="w-full flex items-center gap-2.5 px-3 py-2 rounded-lg text-xs font-medium text-left hover:bg-slate-100 dark:hover:bg-slate-800 text-slate-800 dark:text-slate-200 transition-colors cursor-pointer"
                  >
                    {copied ? <Check className="w-4 h-4 text-emerald-500" /> : <Share2 className="w-4 h-4 text-amber-500" />}
                    <div>
                      <div className="font-semibold">{copied ? 'Link Copied!' : 'Copy Shareable Link'}</div>
                      <div className="text-[10px] text-slate-500 dark:text-slate-400">Direct deep link to current view</div>
                    </div>
                  </button>
                </div>
              )}
            </div>

            {/* Admin Controls Trigger */}
            <button
              onClick={onOpenAdmin}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl border text-xs font-semibold transition-all cursor-pointer hover:border-amber-500 bg-amber-50 dark:bg-amber-500/10 border-amber-200 dark:border-amber-500/30 text-amber-700 dark:text-amber-400 shadow-xs"
              title="Admin Access Control & Schedule Settings"
            >
              <Settings className="w-3.5 h-3.5" />
              <span className="hidden sm:inline">Admin & Schedule</span>
            </button>
          </div>

        </div>
      </div>
    </header>
  );
};
