'use client';

import React, { useState, useRef, useEffect } from 'react';
import { Upload, ChevronDown, Building2, User, Search, LogOut, Check } from 'lucide-react';
import { Workspace, Organization, User as UserType } from '@/lib/api';

interface HeaderProps {
  currentUser: UserType | null;
  currentOrg: Organization | null;
  currentWorkspace: Workspace | null;
  workspaces: Workspace[];
  onSelectWorkspace: (ws: Workspace) => void;
  onOpenUpload: () => void;
  onSearchClick: () => void;
  onLogout: () => void;
}

export const Header: React.FC<HeaderProps> = ({
  currentUser,
  currentOrg,
  currentWorkspace,
  workspaces,
  onSelectWorkspace,
  onOpenUpload,
  onSearchClick,
  onLogout
}) => {
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
    <header className="h-16 bg-slate-900/90 backdrop-blur border-b border-slate-800 flex items-center justify-between px-6 z-10 sticky top-0">
      {/* Workspace Switcher */}
      <div className="flex items-center gap-4 relative" ref={dropdownRef}>
        <div 
          onClick={() => setIsWsDropdownOpen(!isWsDropdownOpen)}
          className="flex items-center gap-2 bg-slate-800/80 hover:bg-slate-800 border border-slate-700/60 px-3 py-1.5 rounded-lg cursor-pointer transition select-none"
        >
          <Building2 className="w-4 h-4 text-indigo-400" />
          <div className="text-left">
            <div className="text-xs font-semibold text-white">
              {currentWorkspace ? currentWorkspace.name : 'Select Workspace'}
            </div>
            <div className="text-[10px] text-slate-400">
              {currentOrg ? currentOrg.name : 'Organization'}
            </div>
          </div>
          <ChevronDown className={`w-3.5 h-3.5 text-slate-400 ml-1 transition-transform ${isWsDropdownOpen ? 'rotate-180' : ''}`} />
        </div>

        {isWsDropdownOpen && (
          <div className="absolute top-12 left-0 w-72 bg-slate-900 border border-slate-700/80 rounded-xl shadow-2xl py-2 z-50">
            <div className="px-3 py-1.5 text-[10px] uppercase font-semibold text-slate-400 tracking-wider">
              Available Workspaces
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
                    className={`w-full px-3 py-2 text-left flex items-center justify-between transition cursor-pointer ${
                      isSelected ? 'bg-indigo-600/20 text-indigo-300' : 'text-slate-300 hover:bg-slate-800'
                    }`}
                  >
                    <div>
                      <div className="text-xs font-medium">{ws.name}</div>
                      <div className="text-[10px] text-slate-400">{ws.organization_name} • Role: {ws.role}</div>
                    </div>
                    {isSelected && <Check className="w-3.5 h-3.5 text-indigo-400" />}
                  </button>
                );
              })}
            </div>
          </div>
        )}
      </div>

      {/* Global Quick Search & Actions */}
      <div className="flex items-center gap-3">
        <div 
          onClick={onSearchClick}
          className="flex items-center gap-2 bg-slate-800/50 hover:bg-slate-800 border border-slate-700/50 px-3.5 py-1.5 rounded-lg text-sm text-slate-400 cursor-pointer w-64 transition"
        >
          <Search className="w-4 h-4 text-slate-400" />
          <span>Ask or search knowledge...</span>
        </div>

        <button
          onClick={onOpenUpload}
          className="flex items-center gap-2 bg-indigo-600 hover:bg-indigo-500 text-white px-3.5 py-1.5 rounded-lg text-sm font-semibold shadow-md shadow-indigo-600/20 transition cursor-pointer"
        >
          <Upload className="w-4 h-4" />
          <span>Upload Document</span>
        </button>

        {/* User profile & Logout */}
        <div className="flex items-center gap-3 pl-3 border-l border-slate-800">
          <div className="flex items-center gap-2.5">
            <div className="w-8 h-8 rounded-full bg-gradient-to-tr from-indigo-500 to-purple-600 flex items-center justify-center text-white text-xs font-bold">
              {getInitials(currentUser)}
            </div>
            <div className="hidden md:block text-left">
              <div className="text-xs font-medium text-white">{getDisplayName(currentUser)}</div>
              <div className="text-[10px] text-indigo-400 font-semibold capitalize">
                {currentOrg?.role || 'Member'}
              </div>
            </div>
          </div>

          <button
            onClick={onLogout}
            className="p-1.5 rounded-lg text-slate-400 hover:text-rose-400 hover:bg-slate-800 transition cursor-pointer"
            title="Sign Out"
          >
            <LogOut className="w-4 h-4" />
          </button>
        </div>
      </div>
    </header>
  );
};
