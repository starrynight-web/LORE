'use client';

import React, { useState, useEffect } from 'react';
import { 
  Lock, 
  KeyRound, 
  Calendar, 
  Clock, 
  ShieldAlert, 
  Sparkles, 
  ArrowRight,
  Settings,
  ShieldCheck,
  Check
} from 'lucide-react';
import { DocsConfig } from '@/lib/docs-types';

interface DocsLockedViewProps {
  config?: DocsConfig;
  message?: string;
  scheduleWindow?: {
    start: string;
    end: string;
    is_active_now: boolean;
  };
  onUnlockWithPasskey: (passkey: string) => void;
  onOpenAdmin: () => void;
  unlockError?: string | null;
}

export const DocsLockedView: React.FC<DocsLockedViewProps> = ({
  config,
  message,
  scheduleWindow,
  onUnlockWithPasskey,
  onOpenAdmin,
  unlockError
}) => {
  const [passkeyInput, setPasskeyInput] = useState('');
  const [timeLeft, setTimeLeft] = useState<{ days: number; hours: number; minutes: number; seconds: number }>({
    days: 0,
    hours: 0,
    minutes: 0,
    seconds: 0
  });

  // Calculate live countdown timer to schedule_start
  useEffect(() => {
    const targetDate = config?.schedule_start 
      ? new Date(config.schedule_start).getTime()
      : new Date('2026-06-10T00:00:00Z').getTime();

    const calculateTime = () => {
      const now = new Date().getTime();
      const difference = targetDate - now;

      if (difference > 0) {
        setTimeLeft({
          days: Math.floor(difference / (1000 * 60 * 60 * 24)),
          hours: Math.floor((difference / (1000 * 60 * 60)) % 24),
          minutes: Math.floor((difference / 1000 / 60) % 60),
          seconds: Math.floor((difference / 1000) % 60),
        });
      } else {
        setTimeLeft({ days: 0, hours: 0, minutes: 0, seconds: 0 });
      }
    };

    calculateTime();
    const interval = setInterval(calculateTime, 1000);
    return () => clearInterval(interval);
  }, [config?.schedule_start]);

  const handleSubmitPasskey = (e: React.FormEvent) => {
    e.preventDefault();
    if (passkeyInput.trim()) {
      onUnlockWithPasskey(passkeyInput.trim());
    }
  };

  const formatDate = (isoString?: string) => {
    if (!isoString) return 'June 10, 2026';
    try {
      const d = new Date(isoString);
      return d.toLocaleDateString('en-US', {
        month: 'short',
        day: 'numeric',
        year: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
        timeZoneName: 'short'
      });
    } catch {
      return isoString;
    }
  };

  return (
    <div className="min-h-[85vh] flex items-center justify-center px-4 py-12">
      <div className="w-full max-w-2xl space-y-8 text-center animate-in fade-in zoom-in-95 duration-200">
        
        {/* Animated Lock Icon */}
        <div className="relative inline-flex items-center justify-center">
          <div className="w-20 h-20 rounded-3xl bg-amber-500/10 border border-amber-500/30 flex items-center justify-center shadow-2xl shadow-amber-500/10">
            <Lock className="w-9 h-9 text-amber-400 animate-pulse" />
          </div>
          <div className="absolute -bottom-2 -right-2 w-7 h-7 rounded-xl bg-slate-900 border border-slate-700 flex items-center justify-center">
            <Calendar className="w-3.5 h-3.5 text-[#a59bf3]" />
          </div>
        </div>

        {/* Headings */}
        <div className="space-y-3">
          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full text-xs font-bold border bg-amber-50 dark:bg-amber-500/10 border-amber-200 dark:border-amber-500/30 text-amber-700 dark:text-amber-400 shadow-xs"
          >
            <Clock className="w-3.5 h-3.5" />
            <span>Scheduled Showcase Window</span>
          </div>

          <h1 className="text-3xl sm:text-4xl font-extrabold tracking-tight text-[var(--foreground)]">
            Documentation Access Restricted
          </h1>

          <p className="text-sm text-[var(--muted-foreground)] max-w-lg mx-auto leading-relaxed">
            {message || "LORE Enterprise Documentation & YC Pitch Deck is reserved for the official judging and investor showcase period (June 10 - June 14)."}
          </p>
        </div>

        {/* Scheduled Window Cards */}
        <div className="p-6 rounded-3xl border bg-[var(--card)] border-[var(--border)] shadow-[var(--lore-card-shadow)] shadow-xl shadow-slate-200/50 dark:shadow-2xl space-y-6"
        >
          <div className="flex flex-col sm:flex-row items-center justify-around gap-4 text-xs font-mono border-b border-[var(--border)] pb-5">
            <div className="text-center sm:text-left">
              <span className="text-[10px] text-slate-400 uppercase tracking-wider block">Window Opens</span>
              <span className="text-sm font-bold text-[#7c6fd6] dark:text-[#a59bf3]">
                {formatDate(config?.schedule_start || '2026-06-10T00:00:00Z')}
              </span>
            </div>

            <div className="hidden sm:block text-slate-400 font-bold">→</div>

            <div className="text-center sm:text-right">
              <span className="text-[10px] text-slate-400 uppercase tracking-wider block">Window Closes</span>
              <span className="text-sm font-bold text-purple-600 dark:text-purple-400">
                {formatDate(config?.schedule_end || '2026-06-14T23:59:59Z')}
              </span>
            </div>
          </div>

          {/* Countdown Clock */}
          <div className="space-y-2">
            <span className="text-[10px] font-bold text-[var(--muted-foreground)] uppercase tracking-wider block">
              Time Until Public Showcase Opens
            </span>
            <div className="grid grid-cols-4 gap-3 max-w-md mx-auto">
              <div className="p-3 rounded-2xl bg-[var(--background)] border border-[var(--border)]/60">
                <div className="text-2xl sm:text-3xl font-extrabold font-mono text-[var(--foreground)]">{timeLeft.days}</div>
                <div className="text-[9px] font-bold text-[var(--muted-foreground)] uppercase mt-0.5">Days</div>
              </div>
              <div className="p-3 rounded-2xl bg-[var(--background)] border border-[var(--border)]/60">
                <div className="text-2xl sm:text-3xl font-extrabold font-mono text-[var(--foreground)]">{timeLeft.hours}</div>
                <div className="text-[9px] font-bold text-[var(--muted-foreground)] uppercase mt-0.5">Hours</div>
              </div>
              <div className="p-3 rounded-2xl bg-[var(--background)] border border-[var(--border)]/60">
                <div className="text-2xl sm:text-3xl font-extrabold font-mono text-[var(--foreground)]">{timeLeft.minutes}</div>
                <div className="text-[9px] font-bold text-[var(--muted-foreground)] uppercase mt-0.5">Mins</div>
              </div>
              <div className="p-3 rounded-2xl bg-[var(--background)] border border-[var(--border)]/60">
                <div className="text-2xl sm:text-3xl font-extrabold font-mono text-[var(--foreground)]">{timeLeft.seconds}</div>
                <div className="text-[9px] font-bold text-[var(--muted-foreground)] uppercase mt-0.5">Secs</div>
              </div>
            </div>
          </div>

          {/* Judge / Evaluator Passkey Unlock Form */}
          <div className="pt-4 border-t border-[var(--border)] space-y-3">
            <div className="flex items-center justify-between text-xs">
              <span className="font-bold text-slate-800 dark:text-slate-300 flex items-center gap-1.5">
                <KeyRound className="w-3.5 h-3.5 text-amber-500" />
                <span>Judge & Investor Passkey Unlock</span>
              </span>
              <span className="text-[10px] text-slate-500 font-mono">
                Default: LORE2026
              </span>
            </div>

            <form onSubmit={handleSubmitPasskey} className="flex gap-2">
              <input
                type="password"
                placeholder="Enter passkey (e.g. LORE2026)..."
                value={passkeyInput}
                onChange={(e) => setPasskeyInput(e.target.value)}
                className="flex-1 px-4 py-2.5 rounded-xl border bg-[var(--background)] border-[var(--border)] text-xs text-[var(--foreground)] placeholder-slate-400 focus:outline-none focus:border-[#7c6fd6] focus:bg-white transition-colors shadow-xs"
              />
              <button
                type="submit"
                className="px-5 py-2.5 rounded-xl bg-[#7c6fd6] hover:bg-[#5f52c4] text-white text-xs font-bold transition-all shadow-md flex items-center gap-1.5 shrink-0 cursor-pointer"
              >
                <span>Unlock Preview</span>
                <ArrowRight className="w-3.5 h-3.5" />
              </button>
            </form>

            {unlockError && (
              <p className="text-xs text-red-600 dark:text-red-400 font-semibold text-left animate-in fade-in">
                {unlockError}
              </p>
            )}
          </div>
        </div>

        {/* Admin Access Controls Link */}
        <div className="pt-2 flex items-center justify-center gap-4 text-xs text-[var(--text-muted)]">
          <span>Are you an administrator?</span>
          <button
            onClick={onOpenAdmin}
            className="flex items-center gap-1.5 font-bold text-amber-400 hover:text-amber-300 underline cursor-pointer"
          >
            <Settings className="w-3.5 h-3.5" />
            <span>Open Admin Controls & Scheduling</span>
          </button>
        </div>

      </div>
    </div>
  );
};
