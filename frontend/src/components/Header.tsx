'use client';

import React, { useState, useRef, useEffect } from 'react';
import { 
  Upload, 
  ChevronDown, 
  Search, 
  LogOut, 
  Check, 
  Menu, 
  PanelLeft, 
  Sun, 
  Moon, 
  FileUp, 
  Archive, 
  Globe, 
  Mail, 
  User as UserIcon,
  Sparkles
} from 'lucide-react';
import { Workspace, Organization, User as UserType } from '@/lib/api';
import { useI18n, Language } from '@/lib/i18n';
import { useTheme } from '@/lib/theme';

interface HeaderProps {
  currentUser: UserType | null;
  currentOrg: Organization | null;
  currentWorkspace: Workspace | null;
  workspaces: Workspace[];
  isGuestMode?: boolean;
  onSelectWorkspace: (ws: Workspace) => void;
  onOpenUpload: (mode?: 'files' | 'zip' | 'scraper') => void;
  onSearchClick: () => void;
  onLogout: () => void;
  onOpenAuthModal?: () => void;
  isSidebarOpen?: boolean;
  onToggleSidebar?: () => void;
  onNavigateTab?: (tab: string) => void;
  onOpenWorkspaceSwitcher?: () => void;
}

export const Header: React.FC<HeaderProps> = ({
  currentUser,
  currentOrg,
  currentWorkspace,
  workspaces,
  isGuestMode = false,
  onSelectWorkspace,
  onOpenUpload,
  onSearchClick,
  onLogout,
  onOpenAuthModal,
  isSidebarOpen = true,
  onToggleSidebar,
  onNavigateTab,
  onOpenWorkspaceSwitcher
}) => {
  const { t, language, setLanguage } = useI18n();
  const { theme, toggleTheme } = useTheme();
  const isDark = theme === 'dark';

  const [isUploadMenuOpen, setIsUploadMenuOpen] = useState(false);
  const [isProfileMenuOpen, setIsProfileMenuOpen] = useState(false);

  const uploadMenuRef = useRef<HTMLDivElement>(null);
  const profileMenuRef = useRef<HTMLDivElement>(null);

  // Close menus on outside click
  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (uploadMenuRef.current && !uploadMenuRef.current.contains(e.target as Node)) {
        setIsUploadMenuOpen(false);
      }
      if (profileMenuRef.current && !profileMenuRef.current.contains(e.target as Node)) {
        setIsProfileMenuOpen(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  const getInitials = (user: UserType | null) => {
    if (!user) return isGuestMode ? 'GS' : 'EU';
    if (user.first_name && user.last_name) {
      return `${user.first_name[0]}${user.last_name[0]}`.toUpperCase();
    }
    return user.username.slice(0, 2).toUpperCase();
  };

  const getDisplayName = (user: UserType | null) => {
    if (!user) return isGuestMode ? 'Guest Admin' : 'Enterprise User';
    if (user.first_name || user.last_name) {
      return `${user.first_name} ${user.last_name}`.trim();
    }
    return user.username;
  };

  const currentRole = currentWorkspace?.role || currentOrg?.role || (isGuestMode ? 'Demo Admin' : 'Member');

  return (
    <header 
      className="h-[52px] border-b flex items-center justify-between px-4 z-30 sticky top-0 transition-colors shrink-0"
      style={{
        backgroundColor: isDark ? 'rgba(28, 28, 30, 0.72)' : 'rgba(255, 255, 255, 0.72)',
        backdropFilter: 'blur(20px) saturate(180%)',
        WebkitBackdropFilter: 'blur(20px) saturate(180%)',
        borderColor: 'var(--hairline)',
      }}
    >
      {/* LEFT CLUSTER: Ghost sidebar-toggle · "LORE" 13/700 + "Knowledge Grid" 11 overline + quiet "· {workspace} ▾" pull-down */}
      <div className="flex items-center gap-2.5 min-w-0">
        {onToggleSidebar && (
          <button
            onClick={onToggleSidebar}
            className="w-7 h-7 rounded-md flex items-center justify-center text-[#6E6E73] hover:text-[var(--text-primary)] hover:bg-black/5 dark:hover:bg-white/10 active:bg-black/10 transition-colors cursor-pointer shrink-0"
            title={isSidebarOpen ? "Collapse sidebar" : "Expand sidebar"}
          >
            <PanelLeft className="w-4 h-4" />
          </button>
        )}

        <div className="flex items-baseline gap-1.5 select-none shrink-0">
          <span className="text-[13px] font-bold text-[var(--text-primary)] tracking-tight">
            LORE
          </span>
          <span className="sonoma-overline text-[#86868B] text-[10px] hidden sm:inline">
            Knowledge Grid
          </span>
        </div>

        {/* Quiet workspace pull-down (no box) */}
        <button
          onClick={onOpenWorkspaceSwitcher}
          className="flex items-center gap-1 text-[12px] text-[#6E6E73] hover:text-[var(--text-primary)] px-1.5 py-0.5 rounded transition-colors cursor-pointer truncate max-w-[160px] sm:max-w-[240px]"
          title="Click to switch workspace"
        >
          <span className="text-[#86868B]">·</span>
          <span className="truncate font-medium">{currentWorkspace?.name || 'Default Workspace'}</span>
          <ChevronDown className="w-3 h-3 text-[#86868B] shrink-0" />
        </button>
      </div>

      {/* CENTER CLUSTER: Search 380×28, inset track, radius 8, magnifier + ⌘K keycap chip */}
      <div className="flex-1 max-w-[380px] mx-4 hidden md:block">
        <button
          onClick={onSearchClick}
          className="w-full h-7 px-2.5 rounded-lg border flex items-center justify-between text-xs text-[#6E6E73] cursor-pointer transition-colors hover:border-[#007AFF]/40"
          style={{
            backgroundColor: 'var(--inset)',
            borderColor: 'var(--hairline)',
          }}
        >
          <div className="flex items-center gap-2 min-w-0">
            <Search className="w-3.5 h-3.5 text-[#86868B] shrink-0" />
            <span className="truncate text-[12px]">{t('header.search_placeholder') || 'Search workspace, rules, docs...'}</span>
          </div>
          <kbd 
            className="px-1.5 py-0.5 text-[10px] font-mono rounded border text-[#86868B] bg-white/60 dark:bg-black/20 shrink-0"
            style={{ borderColor: 'var(--hairline)' }}
          >
            ⌘K
          </kbd>
        </button>
      </div>

      {/* RIGHT CLUSTER: Exactly ONE filled control: split [Upload Document ▾] filled blue · divider · EN|বাংলা · ghost theme · divider · avatar */}
      <div className="flex items-center gap-2.5 shrink-0">
        {/* Split [Upload Document ▾] Button (Filled blue #007AFF) */}
        <div className="relative inline-flex items-center rounded-lg shadow-xs" ref={uploadMenuRef}>
          <button
            onClick={() => onOpenUpload('files')}
            className="h-7 px-2.5 rounded-l-lg text-xs font-semibold text-white flex items-center gap-1.5 cursor-pointer active:brightness-95 transition-all"
            style={{ backgroundColor: '#007AFF' }}
            title="Upload document"
          >
            <Upload className="w-3.5 h-3.5 stroke-[2.2]" />
            <span className="hidden sm:inline">Upload Document</span>
          </button>
          <button
            onClick={() => setIsUploadMenuOpen(!isUploadMenuOpen)}
            className="h-7 px-1.5 rounded-r-lg text-white border-l border-white/20 flex items-center justify-center cursor-pointer active:brightness-95 transition-all"
            style={{ backgroundColor: '#007AFF' }}
            title="Upload options"
          >
            <ChevronDown className="w-3 h-3 stroke-[2.5]" />
          </button>

          {/* Upload Dropdown Menu */}
          {isUploadMenuOpen && (
            <div 
              className="absolute right-0 top-8 w-48 sonoma-card sonoma-elevation py-1 z-50 animate-in fade-in zoom-in-95 duration-100"
              style={{
                backgroundColor: 'var(--card)',
                borderColor: 'var(--hairline)',
              }}
            >
              <button
                onClick={() => {
                  setIsUploadMenuOpen(false);
                  onOpenUpload('files');
                }}
                className="w-full px-3 py-1.5 text-left text-xs font-medium text-[var(--text-primary)] hover:bg-[var(--hover)] flex items-center gap-2 cursor-pointer"
              >
                <FileUp className="w-3.5 h-3.5 text-[#007AFF]" />
                <span>Files…</span>
              </button>
              <button
                onClick={() => {
                  setIsUploadMenuOpen(false);
                  onOpenUpload('zip');
                }}
                className="w-full px-3 py-1.5 text-left text-xs font-medium text-[var(--text-primary)] hover:bg-[var(--hover)] flex items-center gap-2 cursor-pointer"
              >
                <Archive className="w-3.5 h-3.5 text-[#5E5CE6]" />
                <span>ZIP Archive…</span>
              </button>
              <button
                onClick={() => {
                  setIsUploadMenuOpen(false);
                  onOpenUpload('scraper');
                }}
                className="w-full px-3 py-1.5 text-left text-xs font-medium text-[var(--text-primary)] hover:bg-[var(--hover)] flex items-center gap-2 cursor-pointer"
              >
                <Globe className="w-3.5 h-3.5 text-[#FF9500]" />
                <span>Web Source…</span>
              </button>
              <button
                onClick={() => {
                  setIsUploadMenuOpen(false);
                  if (onNavigateTab) onNavigateTab('email_connect');
                }}
                className="w-full px-3 py-1.5 text-left text-xs font-medium text-[var(--text-primary)] hover:bg-[var(--hover)] flex items-center gap-2 cursor-pointer border-t"
                style={{ borderColor: 'var(--hairline)' }}
              >
                <Mail className="w-3.5 h-3.5 text-[#34C759]" />
                <span>Email Sync (Gmail)…</span>
              </button>
            </div>
          )}
        </div>

        {/* Hairline Divider */}
        <div className="w-px h-5 bg-[var(--hairline)]" />

        {/* EN|বাংলা Segmented Control (28px) */}
        <div 
          className="h-7 p-0.5 rounded-lg border flex items-center select-none"
          style={{
            backgroundColor: 'var(--inset)',
            borderColor: 'var(--hairline)',
          }}
          role="group"
          aria-label="Language selector"
        >
          <button
            type="button"
            onClick={() => setLanguage('en')}
            className="h-6 px-2 text-[11px] font-semibold rounded-md transition-all cursor-pointer"
            style={{
              backgroundColor: language === 'en' ? 'var(--card)' : 'transparent',
              color: language === 'en' ? 'var(--text-primary)' : '#86868B',
              boxShadow: language === 'en' ? '0 1px 2px rgba(0,0,0,0.06)' : 'none',
            }}
          >
            EN
          </button>
          <button
            type="button"
            onClick={() => setLanguage('bn')}
            className="h-6 px-2 text-[11px] font-semibold rounded-md transition-all cursor-pointer"
            style={{
              backgroundColor: language === 'bn' ? 'var(--card)' : 'transparent',
              color: language === 'bn' ? 'var(--text-primary)' : '#86868B',
              boxShadow: language === 'bn' ? '0 1px 2px rgba(0,0,0,0.06)' : 'none',
            }}
          >
            বাংলা
          </button>
        </div>

        {/* Ghost Theme Icon (28px) */}
        <button
          onClick={toggleTheme}
          className="w-7 h-7 rounded-md flex items-center justify-center text-[#6E6E73] hover:text-[var(--text-primary)] hover:bg-black/5 dark:hover:bg-white/10 active:bg-black/10 transition-colors cursor-pointer"
          title={isDark ? "Switch to Light mode" : "Switch to Dark mode"}
        >
          {isDark ? (
            <Moon className="w-3.5 h-3.5 text-[#0A84FF]" />
          ) : (
            <Sun className="w-3.5 h-3.5 text-[#FF9500]" />
          )}
        </button>

        {/* Hairline Divider */}
        <div className="w-px h-5 bg-[var(--hairline)] hidden sm:block" />

        {/* 28px Avatar + Name 12/600 over Role 10/500 → Profile Menu */}
        <div className="relative" ref={profileMenuRef}>
          <button
            onClick={() => setIsProfileMenuOpen(!isProfileMenuOpen)}
            className="flex items-center gap-2 p-0.5 rounded-lg hover:bg-black/5 dark:hover:bg-white/10 cursor-pointer transition-colors"
          >
            {/* 28px Avatar */}
            <div 
              className="w-7 h-7 rounded-full flex items-center justify-center text-[11px] font-bold text-white shrink-0 shadow-2xs"
              style={{
                backgroundColor: isGuestMode ? '#8E8E93' : '#007AFF',
              }}
            >
              {getInitials(currentUser)}
            </div>

            {/* Name 12/600 over Role 10/500 */}
            <div className="hidden lg:flex flex-col text-left leading-tight">
              <span className="text-[12px] font-semibold text-[var(--text-primary)] truncate max-w-[110px]">
                {getDisplayName(currentUser)}
              </span>
              <span className="text-[10px] font-medium text-[#6E6E73] capitalize truncate max-w-[110px]">
                {currentRole}
              </span>
            </div>

            <ChevronDown className="w-3 h-3 text-[#86868B] hidden lg:block" />
          </button>

          {/* Profile Menu Dropdown */}
          {isProfileMenuOpen && (
            <div 
              className="absolute right-0 top-9 w-60 sonoma-card sonoma-elevation p-2 z-50 animate-in fade-in zoom-in-95 duration-100 space-y-2"
              style={{
                backgroundColor: 'var(--card)',
                borderColor: 'var(--hairline)',
              }}
            >
              <div className="p-2 rounded-lg bg-[var(--inset)]">
                <div className="text-xs font-bold text-[var(--text-primary)]">
                  {getDisplayName(currentUser)}
                </div>
                <div className="text-[11px] text-[#6E6E73] mt-0.5">
                  {currentUser?.email || (isGuestMode ? 'admin@northstar.demo' : 'guest@lore.enterprise')}
                </div>
                <div className="flex items-center gap-1.5 mt-2">
                  <span className="text-[10px] font-semibold uppercase px-1.5 py-0.2 rounded bg-black/5 dark:bg-white/10 text-[var(--text-primary)]">
                    {currentRole}
                  </span>
                  <span className="text-[10px] font-bold text-[#007AFF] px-1.5 py-0.2 rounded bg-[#007AFF]/10">
                    Sovereign Grid
                  </span>
                </div>
              </div>

              {isGuestMode ? (
                onOpenAuthModal && (
                  <button
                    onClick={() => {
                      setIsProfileMenuOpen(false);
                      onOpenAuthModal();
                    }}
                    className="w-full px-2.5 py-1.5 rounded-md text-xs font-medium text-[var(--text-primary)] hover:bg-[var(--hover)] flex items-center gap-2 cursor-pointer"
                  >
                    <UserIcon className="w-3.5 h-3.5 text-[#007AFF]" />
                    <span>Sign In to Account</span>
                  </button>
                )
              ) : (
                <button
                  onClick={() => {
                    setIsProfileMenuOpen(false);
                    onLogout();
                  }}
                  className="w-full px-2.5 py-1.5 rounded-md text-xs font-medium text-[#FF3B30] hover:bg-[var(--hover)] flex items-center gap-2 cursor-pointer"
                >
                  <LogOut className="w-3.5 h-3.5" />
                  <span>Sign Out</span>
                </button>
              )}
            </div>
          )}
        </div>
      </div>
    </header>
  );
};
