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
import { DocsConfig } from '@/lib/docs-types';
import { getStandaloneDocsManifest } from '@/data/docsData';
import { useTheme } from 'next-themes';

export type DocsMode = 'pitch_deck' | 'whitepaper' | 'live_ops' | 'team';

interface DocsHeaderProps {
  mode: DocsMode;
  onModeChange: (mode: DocsMode) => void;
  searchQuery: string;
  onSearchChange: (q: string) => void;
  config?: DocsConfig;
  isAdmin: boolean;
  onOpenAdmin: () => void;
  currentUser?: string;
  onSignOut?: () => void;
}

export const DocsHeader: React.FC<DocsHeaderProps> = ({
  mode,
  onModeChange,
  searchQuery,
  onSearchChange,
  config,
  isAdmin,
  onOpenAdmin,
  currentUser,
  onSignOut,
}) => {
  const { resolvedTheme, setTheme } = useTheme();
  const isDark = resolvedTheme === 'dark';
  const toggleTheme = () => setTheme(isDark ? 'light' : 'dark');
  const [showExportMenu, setShowExportMenu] = useState(false);
  const [copied, setCopied] = useState(false);

  const handleCopyLink = () => {
    if (typeof window !== 'undefined') {
      const url = `${window.location.origin}/enterprise/docs?mode=${mode}`;
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

  
  const handleDownloadMarkdown = () => {
    setShowExportMenu(false);
    try {
      const manifest = getStandaloneDocsManifest();
      if (!manifest.whitepaper) return;
      let md = `# ${manifest.whitepaper.title}\nVersion: ${manifest.whitepaper.version}\n\n`;
      const sec = manifest.whitepaper.sections || {};
      for (const [k, v] of Object.entries(sec)) {
        if (typeof v === 'string') {
          md += `## ${k.toUpperCase()}\n\n${v}\n\n`;
        } else if (v && typeof v === 'object') {
          const heading = (v as any).heading || k.toUpperCase();
          const content = (v as any).content || JSON.stringify(v, null, 2);
          md += `## ${heading}\n\n${content}\n\n`;
        }
      }
      const blob = new Blob([md], { type: 'text/markdown;charset=utf-8;' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `LORE-Enterprise-Whitepaper-v2.0.md`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } catch (err) {
      console.error('Failed to export markdown:', err);
    }
  };

  const handleDownloadJSON = () => {
    setShowExportMenu(false);
    try {
      const manifest = getStandaloneDocsManifest();
      const blob = new Blob([JSON.stringify(manifest, null, 2)], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `LORE-Enterprise-Docs-Manifest.json`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } catch (err) {
      console.error('Failed to export JSON:', err);
    }
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
                  background: 'linear-gradient(135deg, var(--lavender-deep) 0%, var(--lavender-active) 100%)',
                  color: 'var(--accent-fg)',
                }}
              >
                <ShieldCheck className="w-5 h-5 text-white" />
              </div>
              <div className="hidden sm:block">
                <div className="flex items-center gap-1.5">
                  <span className="font-extrabold text-sm tracking-tight text-[var(--foreground)]">
                    LORE
                  </span>
                  <span className="px-1.5 py-0.5 rounded text-[10px] font-bold tracking-wide uppercase bg-[var(--well-sky-bg)] text-[var(--well-sky-fg)] border border-[var(--well-sky-fg)]/20">
                    /docs
                  </span>
                </div>
                <p className="text-[10px] text-[var(--muted-foreground)] font-mono leading-none mt-0.5">
                  v2.0.0-enterprise
                </p>
              </div>
            </a>

            {/* Publishing Status Badge */}
            {config && (
              <div className="hidden md:flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px] font-medium border"
                style={{
                  backgroundColor: config.admin_override
                    ? 'var(--well-sage-bg)'
                    : config.is_currently_open
                    ? 'var(--well-sage-bg)'
                    : 'var(--well-amber-bg)',
                  borderColor: config.admin_override
                    ? 'var(--sage-soft)'
                    : config.is_currently_open
                    ? 'var(--sage-soft)'
                    : 'var(--well-amber-bg)',
                  color: config.admin_override
                    ? 'var(--sage-deep)'
                    : config.is_currently_open
                    ? 'var(--sage-deep)'
                    : 'var(--well-amber-fg)'
                }}
                title={config.admin_override ? 'Admin Override Active' : `Schedule Window: June 10 - June 14`}
              >
                <span className="w-2 h-2 rounded-full animate-pulse"
                  style={{ backgroundColor: config.is_currently_open ? 'var(--sage-deep)' : 'var(--well-amber-fg)' }}
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
                  ? 'bg-[#7c6fd6] text-white shadow-md shadow-blue-500/20'
                  : 'text-[var(--muted-foreground)] hover:text-slate-900 dark:hover:text-white hover:bg-white dark:hover:bg-slate-800/50'
              }`}
            >
              <Sparkles className="w-3.5 h-3.5" />
              <span>Pitch Deck</span>
            </button>

            <button
              onClick={() => onModeChange('whitepaper')}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold transition-all ${
                mode === 'whitepaper'
                  ? 'bg-[#7c6fd6] text-white shadow-md shadow-blue-500/20'
                  : 'text-[var(--muted-foreground)] hover:text-slate-900 dark:hover:text-white hover:bg-white dark:hover:bg-slate-800/50'
              }`}
            >
              <FileText className="w-3.5 h-3.5" />
              <span>Technical Whitepaper</span>
            </button>

            <button
              onClick={() => onModeChange('live_ops')}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold transition-all ${
                mode === 'live_ops'
                  ? 'bg-[#7c6fd6] text-white shadow-md shadow-blue-500/20'
                  : 'text-[var(--muted-foreground)] hover:text-slate-900 dark:hover:text-white hover:bg-white dark:hover:bg-slate-800/50'
              }`}
            >
              <Activity className="w-3.5 h-3.5" />
              <span>Live Ops</span>
            </button>

            <button
              onClick={() => onModeChange('team')}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold transition-all ${
                mode === 'team'
                  ? 'bg-[#7c6fd6] text-white shadow-md shadow-blue-500/20'
                  : 'text-[var(--muted-foreground)] hover:text-slate-900 dark:hover:text-white hover:bg-white dark:hover:bg-slate-800/50'
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
                className="w-full pl-8 pr-3 py-1.5 text-xs rounded-xl border bg-white dark:bg-slate-900/60 border-[var(--border)] focus:outline-none focus:border-[#7c6fd6] text-[var(--foreground)] placeholder-slate-400 transition-colors shadow-xs"
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
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl border text-xs font-semibold transition-all cursor-pointer bg-white dark:bg-slate-800/70 border-[var(--border)] text-slate-700 dark:text-slate-200 hover:border-[#7c6fd6] shadow-xs"
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
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl border text-xs font-semibold transition-all cursor-pointer bg-white dark:bg-slate-800/70 border-[var(--border)] text-slate-700 dark:text-slate-200 hover:border-[#7c6fd6] shadow-xs"
              >
                <Download className="w-3.5 h-3.5 text-[#7c6fd6]" />
                <span className="hidden sm:inline">Export</span>
                <ChevronDown className="w-3 h-3 text-slate-400" />
              </button>

              {showExportMenu && (
                <div 
                  className="absolute right-0 mt-2 w-56 rounded-xl border shadow-2xl p-1.5 z-50 animate-in fade-in zoom-in-95 backdrop-blur-md bg-[var(--card)] border-[var(--border)] shadow-[var(--lore-card-shadow)] text-[var(--foreground)]"
                >
                  <button
                    onClick={handlePrint}
                    className="w-full flex items-center gap-2.5 px-3 py-2 rounded-lg text-xs font-medium text-left hover:bg-slate-100 dark:hover:bg-slate-800 text-[var(--foreground)] transition-colors cursor-pointer"
                  >
                    <Printer className="w-4 h-4 text-emerald-500" />
                    <div>
                      <div className="font-semibold">Print / Save as PDF</div>
                      <div className="text-[10px] text-[var(--muted-foreground)]">Clean, print-ready document</div>
                    </div>
                  </button>

                  <button
                    onClick={handleDownloadMarkdown}
                    className="w-full flex items-center gap-2.5 px-3 py-2 rounded-lg text-xs font-medium text-left hover:bg-slate-100 dark:hover:bg-slate-800 text-[var(--foreground)] transition-colors cursor-pointer"
                  >
                    <FileText className="w-4 h-4 text-[#7c6fd6]" />
                    <div>
                      <div className="font-semibold">Download Markdown (.md)</div>
                      <div className="text-[10px] text-[var(--muted-foreground)]">Full technical whitepaper</div>
                    </div>
                  </button>

                  <button
                    onClick={handleDownloadJSON}
                    className="w-full flex items-center gap-2.5 px-3 py-2 rounded-lg text-xs font-medium text-left hover:bg-slate-100 dark:hover:bg-slate-800 text-[var(--foreground)] transition-colors cursor-pointer"
                  >
                    <Download className="w-4 h-4 text-[#8fbc8f]" />
                    <div>
                      <div className="font-semibold">Download JSON (.json)</div>
                      <div className="text-[10px] text-[var(--muted-foreground)]">Structured schema payload</div>
                    </div>
                  </button>

                  <div className="my-1 border-t border-[var(--border)]" />

                  <button
                    onClick={handleCopyLink}
                    className="w-full flex items-center gap-2.5 px-3 py-2 rounded-lg text-xs font-medium text-left hover:bg-slate-100 dark:hover:bg-slate-800 text-[var(--foreground)] transition-colors cursor-pointer"
                  >
                    {copied ? <Check className="w-4 h-4 text-emerald-500" /> : <Share2 className="w-4 h-4 text-amber-500" />}
                    <div>
                      <div className="font-semibold">{copied ? 'Link Copied!' : 'Copy Shareable Link'}</div>
                      <div className="text-[10px] text-[var(--muted-foreground)]">Direct deep link to current view</div>
                    </div>
                  </button>
                </div>
              )}
            </div>

            {/* User Profile & Sign Out */}
            {currentUser && (
              <div className="hidden md:flex items-center gap-2 pl-2 border-l border-[var(--border)] text-xs">
                <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-xl bg-[var(--background)] border border-[var(--border)] text-[var(--foreground)] font-mono text-[11px]">
                  <span className="w-1.5 h-1.5 rounded-full bg-[#5f8f6a]" />
                  <span>{currentUser}</span>
                </div>
                {onSignOut && (
                  <button
                    onClick={onSignOut}
                    className="text-[11px] text-[var(--muted-foreground)] hover:text-red-500 transition-colors cursor-pointer font-medium"
                    title="Sign out of Enterprise Docs"
                  >
                    Sign Out
                  </button>
                )}
              </div>
            )}

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
