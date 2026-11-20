'use client';

import React, { useState } from 'react';
import { 
  X, 
  Settings, 
  Calendar, 
  Clock, 
  Users, 
  ShieldCheck, 
  Save, 
  RotateCcw, 
  KeyRound, 
  AlertCircle, 
  Check, 
  Plus, 
  Trash2,
  Lock,
  Unlock,
  Sparkles
} from 'lucide-react';
import { DocsConfig, DocsTeamMember } from '@/lib/docs-types';

interface DocsAdminModalProps {
  isOpen: boolean;
  onClose: () => void;
  config?: DocsConfig;
  teamData?: {
    team_name: string;
    charter: string;
    members: DocsTeamMember[];
  };
  onSuccess: () => void;
}

export const DocsAdminModal: React.FC<DocsAdminModalProps> = ({
  isOpen,
  onClose,
  config,
  teamData,
  onSuccess
}) => {
  const [activeTab, setActiveTab] = useState<'access' | 'team'>('access');
  const [adminKey, setAdminKey] = useState('lore_admin_secret_2026');

  // Access Control State
  const [isPublic, setIsPublic] = useState(config?.is_public_accessible ?? true);
  const [enforceSchedule, setEnforceSchedule] = useState(config?.enforce_schedule ?? true);
  const [adminOverride, setAdminOverride] = useState(config?.admin_override ?? false);
  const [scheduleStart, setScheduleStart] = useState(
    config?.schedule_start ? config.schedule_start.substring(0, 16) : '2026-06-10T00:00'
  );
  const [scheduleEnd, setScheduleEnd] = useState(
    config?.schedule_end ? config.schedule_end.substring(0, 16) : '2026-06-14T23:59'
  );
  const [closedMessage, setClosedMessage] = useState(
    config?.closed_message || "LORE Enterprise Documentation & YC Pitch Deck is reserved for the official judging and investor showcase period (June 10 - June 14)."
  );
  const [judgePasskey, setJudgePasskey] = useState(config?.judge_passkey || 'LORE2026');

  // Team Management State
  const [teamName, setTeamName] = useState(teamData?.team_name || "LORE Core Systems & AI Architecture");
  const [teamCharter, setTeamCharter] = useState(teamData?.charter || "Building deterministic cryptographic governance for autonomous AI agents.");
  const [members, setMembers] = useState<DocsTeamMember[]>(teamData?.members || []);

  const [isSaving, setIsSaving] = useState(false);
  const [statusMsg, setStatusMsg] = useState<{ type: 'success' | 'error'; text: string } | null>(null);

  if (!isOpen) return null;

  // Presets Handlers
  const handleApplyPreset = (preset: 'default' | 'override' | '24h' | '7d' | 'lockdown') => {
    const now = new Date();
    switch (preset) {
      case 'default':
        setIsPublic(true);
        setEnforceSchedule(true);
        setAdminOverride(false);
        setScheduleStart('2026-06-10T00:00');
        setScheduleEnd('2026-06-14T23:59');
        setStatusMsg({ type: 'success', text: 'Reset to default window: June 10 (00:00) to June 14 (23:59).' });
        break;
      case 'override':
        setIsPublic(true);
        setAdminOverride(true);
        setStatusMsg({ type: 'success', text: 'Admin Override Active: /docs is now immediately visible to all viewers.' });
        break;
      case '24h': {
        setIsPublic(true);
        setEnforceSchedule(true);
        setAdminOverride(false);
        const end24 = new Date(now.getTime() + 24 * 60 * 60 * 1000);
        setScheduleStart(now.toISOString().substring(0, 16));
        setScheduleEnd(end24.toISOString().substring(0, 16));
        setStatusMsg({ type: 'success', text: 'Published for 24-hour judging showcase.' });
        break;
      }
      case '7d': {
        setIsPublic(true);
        setEnforceSchedule(true);
        setAdminOverride(false);
        const end7d = new Date(now.getTime() + 7 * 24 * 60 * 60 * 1000);
        setScheduleStart(now.toISOString().substring(0, 16));
        setScheduleEnd(end7d.toISOString().substring(0, 16));
        setStatusMsg({ type: 'success', text: 'Published for 7-day extended review.' });
        break;
      }
      case 'lockdown':
        setIsPublic(false);
        setAdminOverride(false);
        setStatusMsg({ type: 'success', text: 'Emergency Lockdown: /docs is now restricted.' });
        break;
    }
  };

  const handleAddMember = () => {
    const newMember: DocsTeamMember = {
      id: `member-${Date.now()}`,
      full_name: 'New Core Contributor',
      role: 'Staff Engineer',
      email: 'contributor@lore.internal',
      avatar_url: `https://api.dicebear.com/7.x/bottts/svg?seed=user${members.length + 1}&backgroundColor=0284c7`,
      bio: 'Enterprise systems specialist focusing on high-assurance distributed verification.',
      skills: ['Distributed Systems', 'Python', 'TypeScript']
    };
    setMembers([...members, newMember]);
  };

  const handleUpdateMember = (idx: number, field: keyof DocsTeamMember, val: any) => {
    const updated = [...members];
    updated[idx] = { ...updated[idx], [field]: val };
    setMembers(updated);
  };

  const handleDeleteMember = (idx: number) => {
    setMembers(members.filter((_, i) => i !== idx));
  };

  const handleSave = async () => {
    setIsSaving(true);
    setStatusMsg(null);
    try {
      const updatedConfig = {
        is_public_accessible: isPublic,
        enforce_schedule: enforceSchedule,
        admin_override: adminOverride,
        schedule_start: new Date(scheduleStart).toISOString(),
        schedule_end: new Date(scheduleEnd).toISOString(),
        closed_message: closedMessage,
        judge_passkey: judgePasskey,
        allow_judge_passkey: true
      };

      const updatedTeam = {
        team_name: teamName,
        charter: teamCharter,
        members
      };

      if (typeof window !== 'undefined') {
        localStorage.setItem('lore_docs_config_override', JSON.stringify(updatedConfig));
        localStorage.setItem('lore_docs_team_override', JSON.stringify(updatedTeam));
      }

      setStatusMsg({ type: 'success', text: 'All settings & team data saved to browser memory.' });
      setTimeout(() => {
        onSuccess();
        onClose();
      }, 800);
    } catch (err: any) {
      setStatusMsg({ type: 'error', text: err?.message || 'Failed to save settings.' });
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 dark:bg-black/75 backdrop-blur-md animate-in fade-in duration-150">
      <div 
        className="w-full max-w-3xl rounded-3xl border shadow-2xl flex flex-col max-h-[90vh] overflow-hidden bg-white dark:bg-slate-900 border-[var(--border)] animate-in zoom-in-95 duration-150"
      >
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-[var(--border)] bg-[var(--background)]/60">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-xl bg-amber-50 dark:bg-amber-500/10 border border-amber-200 dark:border-amber-500/30 flex items-center justify-center text-amber-600 dark:text-amber-400">
              <Settings className="w-5 h-5" />
            </div>
            <div>
              <h2 className="font-extrabold text-base text-[var(--foreground)]">
                /docs Admin Controls & Publishing Suite
              </h2>
              <p className="text-xs text-[var(--muted-foreground)] font-mono">
                Manage public visibility, schedule showcase windows, and edit team cards.
              </p>
            </div>
          </div>

          <button
            onClick={onClose}
            className="p-2 rounded-xl text-slate-400 hover:text-slate-700 dark:hover:text-white hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Tab Navigation */}
        <div className="flex items-center px-6 border-b border-[var(--border)] text-xs font-semibold bg-slate-50/50 dark:bg-slate-900/50">
          <button
            onClick={() => setActiveTab('access')}
            className={`py-3 px-4 border-b-2 transition-all flex items-center gap-2 ${
              activeTab === 'access'
                ? 'border-blue-600 text-[#7c6fd6] dark:text-[#a59bf3] font-bold'
                : 'border-transparent text-[var(--muted-foreground)] hover:text-slate-900 dark:hover:text-white'
            }`}
          >
            <Lock className="w-3.5 h-3.5" />
            <span>1. Access Control & Scheduling</span>
          </button>

          <button
            onClick={() => setActiveTab('team')}
            className={`py-3 px-4 border-b-2 transition-all flex items-center gap-2 ${
              activeTab === 'team'
                ? 'border-blue-600 text-[#7c6fd6] dark:text-[#a59bf3] font-bold'
                : 'border-transparent text-[var(--muted-foreground)] hover:text-slate-900 dark:hover:text-white'
            }`}
          >
            <Users className="w-3.5 h-3.5" />
            <span>2. Team Showcase Editor</span>
          </button>
        </div>

        {/* Modal Body */}
        <div className="flex-1 overflow-y-auto p-6 space-y-6">
          
          {statusMsg && (
            <div className={`p-4 rounded-xl text-xs font-semibold flex items-center gap-2.5 animate-in fade-in ${
              statusMsg.type === 'success' 
                ? 'bg-emerald-50 dark:bg-emerald-500/10 text-emerald-700 dark:text-emerald-400 border border-emerald-200 dark:border-emerald-500/30'
                : 'bg-red-50 dark:bg-red-500/10 text-red-700 dark:text-red-400 border border-red-200 dark:border-red-500/30'
            }`}>
              {statusMsg.type === 'success' ? <Check className="w-4 h-4" /> : <AlertCircle className="w-4 h-4" />}
              <span>{statusMsg.text}</span>
            </div>
          )}

          {activeTab === 'access' ? (
            /* TAB 1: ACCESS CONTROL & SCHEDULING */
            <div className="space-y-6">
              
              {/* Quick Presets */}
              <div className="space-y-2">
                <span className="text-xs font-bold text-[var(--muted-foreground)] uppercase tracking-wider block">
                  Quick Publishing Presets
                </span>
                <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
                  <button
                    onClick={() => handleApplyPreset('default')}
                    className="p-2.5 rounded-xl border border-blue-200 dark:border-[#7c6fd6]/30 bg-blue-50 dark:bg-blue-500/10 hover:bg-blue-100 dark:hover:bg-[#5f52c4]/20 text-blue-700 dark:text-[#a59bf3] text-xs font-bold text-left transition-colors"
                  >
                    🏆 Default (June 10 - 14)
                  </button>
                  <button
                    onClick={() => handleApplyPreset('override')}
                    className="p-2.5 rounded-xl border border-emerald-200 dark:border-emerald-500/30 bg-emerald-50 dark:bg-emerald-500/10 hover:bg-emerald-100 dark:hover:bg-emerald-500/20 text-emerald-700 dark:text-emerald-400 text-xs font-bold text-left transition-colors"
                  >
                    🟢 Instant Live (Override)
                  </button>
                  <button
                    onClick={() => handleApplyPreset('24h')}
                    className="p-2.5 rounded-xl border border-[var(--border)] bg-slate-50 dark:bg-slate-800 hover:bg-slate-100 dark:hover:bg-slate-700 text-[var(--foreground)] text-xs font-bold text-left transition-colors"
                  >
                    ⏱️ Open for 24 Hours
                  </button>
                  <button
                    onClick={() => handleApplyPreset('7d')}
                    className="p-2.5 rounded-xl border border-[var(--border)] bg-slate-50 dark:bg-slate-800 hover:bg-slate-100 dark:hover:bg-slate-700 text-[var(--foreground)] text-xs font-bold text-left transition-colors"
                  >
                    📅 Open for 7 Days
                  </button>
                  <button
                    onClick={() => handleApplyPreset('lockdown')}
                    className="p-2.5 rounded-xl border border-red-200 dark:border-red-500/30 bg-red-50 dark:bg-red-500/10 hover:bg-red-100 dark:hover:bg-red-500/20 text-red-700 dark:text-red-400 text-xs font-bold text-left transition-colors"
                  >
                    🔒 Emergency Lockdown
                  </button>
                </div>
              </div>

              {/* Toggles */}
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div className="p-4 rounded-2xl border border-[var(--border)] bg-slate-50/80 dark:bg-slate-950/40 flex items-center justify-between">
                  <div className="space-y-0.5">
                    <span className="text-xs font-bold text-[var(--foreground)] block">Public Availability</span>
                    <span className="text-[11px] text-[var(--muted-foreground)]">Toggle /docs route on or off</span>
                  </div>
                  <input
                    type="checkbox"
                    checked={isPublic}
                    onChange={(e) => setIsPublic(e.target.checked)}
                    className="w-5 h-5 accent-blue-600 rounded cursor-pointer"
                  />
                </div>

                <div className="p-4 rounded-2xl border border-[var(--border)] bg-slate-50/80 dark:bg-slate-950/40 flex items-center justify-between">
                  <div className="space-y-0.5">
                    <span className="text-xs font-bold text-[var(--foreground)] block">Enforce Schedule Window</span>
                    <span className="text-[11px] text-[var(--muted-foreground)]">Gate access by date range</span>
                  </div>
                  <input
                    type="checkbox"
                    checked={enforceSchedule}
                    onChange={(e) => setEnforceSchedule(e.target.checked)}
                    className="w-5 h-5 accent-blue-600 rounded cursor-pointer"
                  />
                </div>
              </div>

              {/* Admin Instant Override */}
              <div className="p-4 rounded-2xl border border-amber-300 dark:border-amber-500/30 bg-amber-50/80 dark:bg-amber-500/5 flex items-center justify-between">
                <div className="space-y-0.5">
                  <div className="flex items-center gap-2">
                    <Sparkles className="w-4 h-4 text-amber-500 dark:text-amber-400" />
                    <span className="text-xs font-bold text-amber-800 dark:text-amber-300">Admin Instant Override</span>
                  </div>
                  <span className="text-[11px] text-[var(--muted-foreground)]">
                    Bypasses date restrictions immediately for live presentations or judging
                  </span>
                </div>
                <input
                  type="checkbox"
                  checked={adminOverride}
                  onChange={(e) => setAdminOverride(e.target.checked)}
                  className="w-5 h-5 accent-amber-500 rounded cursor-pointer"
                />
              </div>

              {/* Schedule Dates */}
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div className="space-y-1.5">
                  <label className="text-xs font-bold text-[var(--muted-foreground)]">
                    Schedule Window Start (Date & Time)
                  </label>
                  <input
                    type="datetime-local"
                    value={scheduleStart}
                    onChange={(e) => setScheduleStart(e.target.value)}
                    className="w-full px-3 py-2 rounded-xl border border-[var(--border)] bg-white dark:bg-slate-950 text-xs text-[var(--foreground)] focus:outline-none focus:border-[#7c6fd6]"
                  />
                </div>

                <div className="space-y-1.5">
                  <label className="text-xs font-bold text-[var(--muted-foreground)]">
                    Schedule Window End (Date & Time)
                  </label>
                  <input
                    type="datetime-local"
                    value={scheduleEnd}
                    onChange={(e) => setScheduleEnd(e.target.value)}
                    className="w-full px-3 py-2 rounded-xl border border-[var(--border)] bg-white dark:bg-slate-950 text-xs text-[var(--foreground)] focus:outline-none focus:border-[#7c6fd6]"
                  />
                </div>
              </div>

              {/* Closed Message & Judge Passkey */}
              <div className="space-y-4">
                <div className="space-y-1.5">
                  <label className="text-xs font-bold text-[var(--muted-foreground)]">
                    Closed Window Notice (Shown to public during lock)
                  </label>
                  <textarea
                    rows={2}
                    value={closedMessage}
                    onChange={(e) => setClosedMessage(e.target.value)}
                    className="w-full px-3 py-2 rounded-xl border border-[var(--border)] bg-white dark:bg-slate-950 text-xs text-[var(--foreground)] focus:outline-none focus:border-[#7c6fd6]"
                  />
                </div>

                <div className="space-y-1.5">
                  <label className="text-xs font-bold text-[var(--muted-foreground)]">
                    Emergency Judge Passkey (Allows instant evaluator preview)
                  </label>
                  <input
                    type="text"
                    value={judgePasskey}
                    onChange={(e) => setJudgePasskey(e.target.value)}
                    className="w-full px-3 py-2 rounded-xl border border-[var(--border)] bg-white dark:bg-slate-950 text-xs font-mono font-bold text-amber-600 dark:text-amber-300 focus:outline-none focus:border-amber-500"
                  />
                </div>
              </div>

            </div>
          ) : (
            /* TAB 2: TEAM SHOWCASE EDITOR */
            <div className="space-y-6">
              
              <div className="space-y-3">
                <div className="space-y-1.5">
                  <label className="text-xs font-bold text-[var(--muted-foreground)]">Team Name</label>
                  <input
                    type="text"
                    value={teamName}
                    onChange={(e) => setTeamName(e.target.value)}
                    className="w-full px-3 py-2 rounded-xl border border-[var(--border)] bg-white dark:bg-slate-950 text-xs text-[var(--foreground)] font-bold"
                  />
                </div>

                <div className="space-y-1.5">
                  <label className="text-xs font-bold text-[var(--muted-foreground)]">Team Mission Charter</label>
                  <textarea
                    rows={2}
                    value={teamCharter}
                    onChange={(e) => setTeamCharter(e.target.value)}
                    className="w-full px-3 py-2 rounded-xl border border-[var(--border)] bg-white dark:bg-slate-950 text-xs text-[var(--foreground)]"
                  />
                </div>
              </div>

              {/* Members List */}
              <div className="space-y-3">
                <div className="flex items-center justify-between">
                  <span className="text-xs font-bold text-[var(--muted-foreground)] uppercase tracking-wider">
                    Team Members ({members.length})
                  </span>
                  <button
                    onClick={handleAddMember}
                    className="flex items-center gap-1.5 px-3 py-1 rounded-lg text-xs font-bold bg-[#7c6fd6] hover:bg-[#5f52c4] text-white"
                  >
                    <Plus className="w-3.5 h-3.5" />
                    <span>Add Member</span>
                  </button>
                </div>

                <div className="space-y-4">
                  {members.map((m, idx) => (
                    <div
                      key={m.id || idx}
                      className="p-4 rounded-2xl border border-[var(--border)] bg-slate-50/80 dark:bg-slate-950/60 space-y-3 relative group"
                    >
                      <button
                        onClick={() => handleDeleteMember(idx)}
                        className="absolute top-3 right-3 text-red-500 hover:text-red-700 dark:hover:text-red-300 p-1.5 rounded-lg hover:bg-red-50 dark:hover:bg-red-500/10"
                        title="Delete member"
                      >
                        <Trash2 className="w-4 h-4" />
                      </button>

                      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 pr-8">
                        <div>
                          <label className="text-[10px] font-bold text-slate-500 uppercase">Full Name</label>
                          <input
                            type="text"
                            value={m.full_name}
                            onChange={(e) => handleUpdateMember(idx, 'full_name', e.target.value)}
                            className="w-full px-2.5 py-1.5 rounded-lg border border-[var(--border)] bg-white dark:bg-slate-900 text-xs text-[var(--foreground)]"
                          />
                        </div>
                        <div>
                          <label className="text-[10px] font-bold text-slate-500 uppercase">Role / Title</label>
                          <input
                            type="text"
                            value={m.role}
                            onChange={(e) => handleUpdateMember(idx, 'role', e.target.value)}
                            className="w-full px-2.5 py-1.5 rounded-lg border border-[var(--border)] bg-white dark:bg-slate-900 text-xs text-[#7c6fd6] dark:text-[#a59bf3] font-semibold"
                          />
                        </div>
                      </div>

                      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                        <div>
                          <label className="text-[10px] font-bold text-slate-500 uppercase">Email Address</label>
                          <input
                            type="email"
                            value={m.email}
                            onChange={(e) => handleUpdateMember(idx, 'email', e.target.value)}
                            className="w-full px-2.5 py-1.5 rounded-lg border border-[var(--border)] bg-white dark:bg-slate-900 text-xs text-[var(--foreground)] font-mono"
                          />
                        </div>
                        <div>
                          <label className="text-[10px] font-bold text-slate-500 uppercase">Avatar URL (Uniform Framing)</label>
                          <input
                            type="text"
                            value={m.avatar_url}
                            onChange={(e) => handleUpdateMember(idx, 'avatar_url', e.target.value)}
                            className="w-full px-2.5 py-1.5 rounded-lg border border-[var(--border)] bg-white dark:bg-slate-900 text-xs text-[var(--foreground)] font-mono"
                          />
                        </div>
                      </div>

                      <div>
                        <label className="text-[10px] font-bold text-slate-500 uppercase">Short Bio</label>
                        <input
                          type="text"
                          value={m.bio}
                          onChange={(e) => handleUpdateMember(idx, 'bio', e.target.value)}
                          className="w-full px-2.5 py-1.5 rounded-lg border border-[var(--border)] bg-white dark:bg-slate-900 text-xs text-[var(--foreground)]"
                        />
                      </div>
                    </div>
                  ))}
                </div>
              </div>

            </div>
          )}

        </div>

        {/* Footer Actions */}
        <div className="px-6 py-4 border-t border-[var(--border)] bg-[var(--background)]/80 flex items-center justify-between text-xs">
          <button
            onClick={onClose}
            className="px-4 py-2 rounded-xl border border-[var(--border)] bg-white dark:bg-slate-900 text-[var(--foreground)] hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors font-semibold"
          >
            Cancel
          </button>

          <button
            onClick={handleSave}
            disabled={isSaving}
            className="flex items-center gap-2 px-6 py-2.5 rounded-xl bg-[#7c6fd6] hover:bg-[#5f52c4] text-white font-bold transition-all shadow-lg shadow-blue-600/30 disabled:opacity-50 cursor-pointer"
          >
            <Save className="w-4 h-4" />
            <span>{isSaving ? 'Publishing Changes...' : 'Save & Publish Live'}</span>
          </button>
        </div>

      </div>
    </div>
  );
};
