'use client';

import React from 'react';
import { Upload, ChevronDown, Building2, User, Search } from 'lucide-react';
import { Workspace, Organization } from '@/lib/api';

interface HeaderProps {
  currentOrg: Organization | null;
  currentWorkspace: Workspace | null;
  workspaces: Workspace[];
  onSelectWorkspace: (ws: Workspace) => void;
  onOpenUpload: () => void;
  onSearchClick: () => void;
}

export const Header: React.FC<HeaderProps> = ({
  currentOrg,
  currentWorkspace,
  workspaces,
  onSelectWorkspace,
  onOpenUpload,
  onSearchClick
}) => {
  return (
    <header className="h-16 bg-slate-900/90 backdrop-blur border-b border-slate-800 flex items-center justify-between px-6 z-10 sticky top-0">
      {/* Workspace Switcher */}
      <div className="flex items-center gap-4">
        <div className="flex items-center gap-2 bg-slate-800/80 hover:bg-slate-800 border border-slate-700/60 px-3 py-1.5 rounded-lg cursor-pointer transition">
          <Building2 className="w-4 h-4 text-indigo-400" />
          <div className="text-left">
            <div className="text-xs font-semibold text-white">
              {currentWorkspace ? currentWorkspace.name : 'Select Workspace'}
            </div>
            <div className="text-[10px] text-slate-400">
              {currentOrg ? currentOrg.name : 'Organization'}
            </div>
          </div>
          <ChevronDown className="w-3.5 h-3.5 text-slate-400 ml-1" />
        </div>
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

        {/* User profile */}
        <div className="flex items-center gap-2.5 pl-3 border-l border-slate-800">
          <div className="w-8 h-8 rounded-full bg-gradient-to-tr from-indigo-500 to-purple-600 flex items-center justify-center text-white text-xs font-bold">
            SC
          </div>
          <div className="hidden md:block text-left">
            <div className="text-xs font-medium text-white">Sarah Chen</div>
            <div className="text-[10px] text-indigo-400 font-semibold">Admin Owner</div>
          </div>
        </div>
      </div>
    </header>
  );
};
