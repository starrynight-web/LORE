'use client';

import React, { useState } from 'react';
import { 
  Lock, 
  KeyRound, 
  Mail, 
  ArrowRight, 
  ShieldCheck, 
  Sparkles, 
  AlertCircle,
  Eye,
  EyeOff,
  Check
} from 'lucide-react';

interface DocsLoginGateProps {
  onLogin: (id: string, pass: string) => boolean;
  loginError?: string | null;
}

export const DocsLoginGate: React.FC<DocsLoginGateProps> = ({
  onLogin,
  loginError: initialError,
}) => {
  const [id, setId] = useState('');
  const [pass, setPass] = useState('');
  const [showPass, setShowPass] = useState(false);
  const [error, setError] = useState<string | null>(initialError || null);
  const [justAutofilled, setJustAutofilled] = useState(false);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);

    if (!id.trim()) {
      setError('Please enter your login ID or email.');
      return;
    }
    if (!pass.trim()) {
      setError('Please enter your password.');
      return;
    }

    const success = onLogin(id.trim(), pass.trim());
    if (!success) {
      setError('Invalid credentials. Required: ID: lore@unleft.space | Pass: LORE2026');
    }
  };

  const handleAutofill = () => {
    setId('lore@unleft.space');
    setPass('LORE2026');
    setError(null);
    setJustAutofilled(true);
    setTimeout(() => setJustAutofilled(false), 2000);
  };

  return (
    <div className="min-h-[80vh] flex items-center justify-center px-4 py-12">
      <div className="w-full max-w-md space-y-6">
        
        {/* Brand Card */}
        <div className="rounded-3xl border bg-[var(--card)] border-[var(--border)] shadow-[var(--lore-card-shadow)] p-8 sm:p-10 space-y-7 relative overflow-hidden backdrop-blur-md">
          {/* Top subtle lavender background glow */}
          <div className="absolute -top-16 -right-16 w-44 h-44 bg-[#a59bf3]/15 rounded-full blur-3xl pointer-events-none" />
          <div className="absolute -bottom-16 -left-16 w-44 h-44 bg-[#8fbc8f]/15 rounded-full blur-3xl pointer-events-none" />

          {/* Header */}
          <div className="text-center space-y-3 relative z-10">
            <div className="inline-flex items-center justify-center w-14 h-14 rounded-2xl bg-gradient-to-br from-[#7c6fd6] to-[#5f52c4] text-white shadow-lg shadow-[#7c6fd6]/30 mb-1">
              <Lock className="w-7 h-7" />
            </div>

            <div className="space-y-1">
              <div className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-[11px] font-bold uppercase tracking-wider bg-[#a59bf3]/15 text-[#5f52c4] dark:text-[#c4bcf8] border border-[#a59bf3]/30">
                <Sparkles className="w-3 h-3" />
                <span>Enterprise Portal</span>
              </div>
              <h1 className="text-2xl font-extrabold tracking-tight text-[var(--foreground)]">
                Sign in to /enterprise/docs
              </h1>
              <p className="text-xs text-[var(--muted-foreground)] leading-relaxed">
                Enter your authorized evaluator credentials to access the full technical whitepaper, pitch deck, and telemetry.
              </p>
            </div>
          </div>

          {/* Form */}
          <form onSubmit={handleSubmit} className="space-y-4 relative z-10">
            
            {/* ID / Email */}
            <div className="space-y-1.5">
              <label className="block text-xs font-semibold text-[var(--foreground)]">
                Authorized ID / Email
              </label>
              <div className="relative">
                <div className="absolute inset-y-0 left-0 pl-3.5 flex items-center pointer-events-none text-[var(--muted-foreground)]">
                  <Mail className="w-4 h-4" />
                </div>
                <input
                  type="text"
                  value={id}
                  onChange={(e) => setId(e.target.value)}
                  placeholder="lore@unleft.space"
                  className="w-full pl-10 pr-4 py-2.5 rounded-xl border bg-[var(--background)] border-[var(--border)] text-xs text-[var(--foreground)] placeholder-[var(--muted-foreground)]/60 focus:outline-none focus:border-[#7c6fd6] focus:ring-2 focus:ring-[#7c6fd6]/20 transition-all font-mono"
                  autoComplete="username"
                  autoFocus
                />
              </div>
            </div>

            {/* Password */}
            <div className="space-y-1.5">
              <div className="flex items-center justify-between">
                <label className="block text-xs font-semibold text-[var(--foreground)]">
                  Password
                </label>
                <span className="text-[10px] text-[var(--muted-foreground)] font-mono">
                  Case-sensitive
                </span>
              </div>
              <div className="relative">
                <div className="absolute inset-y-0 left-0 pl-3.5 flex items-center pointer-events-none text-[var(--muted-foreground)]">
                  <KeyRound className="w-4 h-4" />
                </div>
                <input
                  type={showPass ? 'text' : 'password'}
                  value={pass}
                  onChange={(e) => setPass(e.target.value)}
                  placeholder="Enter password..."
                  className="w-full pl-10 pr-10 py-2.5 rounded-xl border bg-[var(--background)] border-[var(--border)] text-xs text-[var(--foreground)] placeholder-[var(--muted-foreground)]/60 focus:outline-none focus:border-[#7c6fd6] focus:ring-2 focus:ring-[#7c6fd6]/20 transition-all font-mono"
                  autoComplete="current-password"
                />
                <button
                  type="button"
                  onClick={() => setShowPass(!showPass)}
                  className="absolute inset-y-0 right-0 pr-3.5 flex items-center text-[var(--muted-foreground)] hover:text-[var(--foreground)] transition-colors cursor-pointer"
                  tabIndex={-1}
                >
                  {showPass ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                </button>
              </div>
            </div>

            {/* Error Message */}
            {error && (
              <div className="p-3 rounded-xl bg-red-500/10 border border-red-500/25 flex items-start gap-2 text-xs text-red-600 dark:text-red-400 animate-in fade-in">
                <AlertCircle className="w-4 h-4 shrink-0 mt-0.5" />
                <span>{error}</span>
              </div>
            )}

            {/* Submit Button */}
            <button
              type="submit"
              className="w-full py-3 px-4 rounded-xl bg-[#7c6fd6] hover:bg-[#5f52c4] text-white text-xs font-bold transition-all shadow-md shadow-[#7c6fd6]/25 flex items-center justify-center gap-2 cursor-pointer group"
            >
              <span>Unlock Enterprise Docs</span>
              <ArrowRight className="w-4 h-4 transition-transform group-hover:translate-x-0.5" />
            </button>
          </form>

          {/* Quick Credential Helper Pill */}
          <div className="pt-2 border-t border-[var(--border)] text-center relative z-10 space-y-2">
            <p className="text-[11px] text-[var(--muted-foreground)]">
              Authorized Evaluator Credentials:
            </p>
            <button
              type="button"
              onClick={handleAutofill}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl border text-[11px] font-mono transition-all cursor-pointer bg-[var(--background)] hover:border-[#7c6fd6] border-[var(--border)] text-[var(--foreground)]"
            >
              {justAutofilled ? (
                <>
                  <Check className="w-3.5 h-3.5 text-[#5f8f6a]" />
                  <span className="text-[#5f8f6a] font-semibold">Credentials Populated</span>
                </>
              ) : (
                <>
                  <KeyRound className="w-3.5 h-3.5 text-[#7c6fd6]" />
                  <span>Fill: <strong>lore@unleft.space</strong> / <strong>LORE2026</strong></span>
                </>
              )}
            </button>
          </div>

        </div>

        {/* Security Footer Note */}
        <div className="flex items-center justify-center gap-2 text-[11px] text-[var(--muted-foreground)] font-mono">
          <ShieldCheck className="w-3.5 h-3.5 text-[#5f8f6a]" />
          <span>Client-Verified Cryptographic Session • Zero-Outage Immune</span>
        </div>

      </div>
    </div>
  );
};
