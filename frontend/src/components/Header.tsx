'use client';

import React, { useState, useRef, useEffect } from 'react';
import { Upload, ChevronDown, Building2, User, Search, LogOut, Check } from 'lucide-react';
import { Workspace, Organization, User as UserType } from '@/lib/api';
import { useI18n } from '@/lib/i18n';
import { ThemeToggle, LanguageToggle } from '@/components/PremiumToggles';

interface HeaderProps {
  currentUser: UserType | null;
  currentOrg: Organization | null;
  currentWorkspace: Workspace | null;
  workspaces: Workspace[];
  isGuestMode?: boolean;
  onSelectWorkspace: (ws: Workspace) => void;
  onOpenUpload: () => void;
  onSearchClick: () => void;
  onLogout: () => void;
  onOpenAuthModal?: () => void;
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
  onOpenAuthModal
}) => {
  const { t } = useI18n();
  const [isWsDropdownOpen, setIsWsDropdownOpen] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
        setIsWsDropdownOpen(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  const getInitials = (user: UserType | null) => {
    if (!user) return '??';
    if (user.first_name && user.last_name) {
      return `${user.first_name[0]}${user.last_name[0]}`.toUpperCase();
    }
    return user.username.slice(0, 2).toUpperCase();
  };

  const getDisplayName = (user: UserType | null) => {
    if (!user) return 'Enterprise User';
    if (user.first_name || user.last_name) {
      return `${user.first_name} ${user.last_name}`.trim();
    }
    return user.username;
  };

  return (
    <header 
      className="h-16 border-b flex items-center justify-between px-6 z-20 sticky top-0 transition-colors duration-200"
      style={{
        backgroundColor: 'var(--bg-surface)',
        borderColor: 'var(--border-color)',
      }}
    >
      {/* Left: Workspace Switcher */}
      <div className="flex items-center gap-4 relative" ref={dropdownRef}>
        <div 
          onClick={() => setIsWsDropdownOpen(!isWsDropdownOpen)}
          className="flex items-center gap-2.5 px-3.5 py-1.5 rounded-xl cursor-pointer border transition-all duration-200 select-none shadow-sm"
          style={{
            backgroundColor: 'var(--bg-surface-soft)',
            borderColor: isWsDropdownOpen ? 'var(--brand-accent)' : 'var(--border-color)',
          }}
        >
          <Building2 className="w-4 h-4 text-[var(--brand-accent)]" />
          <div className="text-left">
            <div className="text-xs font-semibold text-[var(--text-primary)]">
              {currentWorkspace ? currentWorkspace.name : t('header.select_workspace')}
            </div>
            <div className="text-[10px] text-[var(--text-muted)]">
              {currentOrg ? currentOrg.name : t('header.organization')}
            </div>
          </div>
          <ChevronDown 
            className={`w-3.5 h-3.5 text-[var(--text-muted)] ml-1 transition-transform duration-200 ${
              isWsDropdownOpen ? 'rotate-180' : ''
            }`} 
          />
        </div>

        {isWsDropdownOpen && (
          <div 
            className="absolute top-12 left-0 w-72 border rounded-xl shadow-xl py-2 z-50 animate-in fade-in slide-in-from-top-2 duration-150"
            style={{
              backgroundColor: 'var(--bg-surface)',
              borderColor: 'var(--border-color)',
            }}
          >
            <div className="px-3 py-1.5 text-[10px] uppercase font-bold text-[var(--text-muted)] tracking-wider">
              {t('header.available_workspaces')}
            </div>
            <div className="max-h-60 overflow-y-auto">
              {workspaces.map((ws) => {
                const isSelected = currentWorkspace?.id === ws.id;
                return (
                  <button
                    key={ws.id}
                    onClick={() => {
                      onSelectWorkspace(ws);
                      setIsWsDropdownOpen(false);
                    }}
                    className="w-full px-3 py-2 text-left flex items-center justify-between transition-colors duration-150 cursor-pointer"
                    style={{
                      backgroundColor: isSelected ? 'var(--accent-light)' : 'transparent',
                      color: isSelected ? 'var(--brand-accent)' : 'var(--text-primary)',
                    }}
                  >
                    <div>
                      <div className="text-xs font-semibold">{ws.name}</div>
                      <div className="text-[10px] text-[var(--text-muted)]">
                        {ws.organization_name} • {t('header.role')}: {ws.role}
                      </div>
                    </div>
                    {isSelected && <Check className="w-3.5 h-3.5 text-[var(--brand-accent)]" />}
                  </button>
                );
              })}
            </div>
          </div>
        )}
      </div>

      {/* Middle & Right: Search, Upload, Toggles, User Profile */}
      <div className="flex items-center gap-3">
        {/* Quick Search */}
        <div 
          onClick={onSearchClick}
          className="hidden sm:flex items-center gap-2 border px-3.5 py-1.5 rounded-xl text-sm cursor-pointer w-56 md:w-64 transition-all duration-200 shadow-sm"
          style={{
            backgroundColor: 'var(--bg-surface-soft)',
            borderColor: 'var(--border-color)',
            color: 'var(--text-muted)',
          }}
        >
          <Search className="w-4 h-4 text-[var(--text-muted)]" />
          <span className="truncate text-xs">{t('header.search_placeholder')}</span>
        </div>

        {/* Upload Action */}
        <button
          onClick={onOpenUpload}
          className="flex items-center gap-2 px-3.5 py-1.5 rounded-xl text-xs font-semibold shadow-sm transition-all duration-200 cursor-pointer active:scale-95"
          style={{
            backgroundColor: 'var(--brand-accent)',
            color: 'var(--cta-text)',
          }}
        >
          <Upload className="w-3.5 h-3.5" />
          <span>{t('header.upload_button')}</span>
        </button>

        {/* Language Toggle (Bangla / English) */}
        <div className="pl-1">
          <LanguageToggle />
        </div>

        {/* Custom Sliding-Pill Theme Toggle (78x40px desktop, 68x36px compact) */}
        <div className="pl-1">
          <ThemeToggle />
        </div>

        {/* User profile / Guest Mode */}
        {isGuestMode ? (
          <div 
            className="flex items-center gap-2.5 pl-3 border-l"
            style={{ borderColor: 'var(--border-color)' }}
          >
            <div 
              className="flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium border"
              style={{
                backgroundColor: 'var(--accent-light)',
                borderColor: 'var(--border-color)',
                color: 'var(--brand-accent)',
              }}
            >
              <span className="w-1.5 h-1.5 rounded-full bg-[var(--brand-accent)] animate-pulse" />
              <span className="text-[11px] font-semibold">{t('header.guest_mode')}</span>
            </div>
            {onOpenAuthModal && (
              <button
                onClick={onOpenAuthModal}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-medium border transition-colors cursor-pointer"
                style={{
                  backgroundColor: 'var(--bg-surface-soft)',
                  borderColor: 'var(--border-color)',
                  color: 'var(--text-primary)',
                }}
              >
                <User className="w-3.5 h-3.5 text-[var(--brand-accent)]" />
                <span>{t('header.sign_in')}</span>
              </button>
            )}
          </div>
        ) : (
          <div 
            className="flex items-center gap-3 pl-3 border-l"
            style={{ borderColor: 'var(--border-color)' }}
          >
            <div className="flex items-center gap-2.5">
              <div 
                className="w-8 h-8 rounded-full flex items-center justify-center text-xs font-bold shadow-sm"
                style={{
                  backgroundColor: 'var(--brand-accent)',
                  color: 'var(--cta-text)',
                }}
              >
                {getInitials(currentUser)}
              </div>
              <div className="hidden md:block text-left">
                <div className="text-xs font-semibold text-[var(--text-primary)]">
                  {getDisplayName(currentUser)}
                </div>
                <div className="text-[10px] text-[var(--brand-accent)] font-medium capitalize">
                  {currentOrg?.role || 'Member'}
                </div>
              </div>
            </div>

            <button
              onClick={onLogout}
              className="p-1.5 rounded-lg transition-colors cursor-pointer hover:text-red-500"
              style={{
                color: 'var(--text-muted)',
              }}
              title={t('header.sign_out')}
            >
              <LogOut className="w-4 h-4" />
            </button>
          </div>
        )}
      </div>
    </header>
  );
};
