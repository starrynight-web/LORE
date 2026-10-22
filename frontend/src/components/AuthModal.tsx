'use client';

import React, { useState } from 'react';
import { 
  ShieldCheck, 
  Building2, 
  Lock, 
  User, 
  ArrowRight, 
  CheckCircle2, 
  AlertCircle,
  Sparkles,
  X
} from 'lucide-react';
import { api, User as UserType, Organization } from '@/lib/api';
import { useI18n } from '@/lib/i18n';

interface AuthModalProps {
  onSuccess: (data: { user: UserType; organizations?: Organization[] }) => void;
  onClose?: () => void;
}

export const AuthModal: React.FC<AuthModalProps> = ({ onSuccess, onClose }) => {
  const { t } = useI18n();
  const [mode, setMode] = useState<'signin' | 'register' | 'demo'>('demo');
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [email, setEmail] = useState('');
  const [orgName, setOrgName] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const demoAccounts = [
    {
      role: 'Tenant 1: Admin / Owner',
      name: 'Sarah Chen',
      email: 'admin@northstar.demo',
      pass: 'Northstar2026!',
      org: 'Northstar Digital',
      badge: 'Full Governance & Ingestion Control'
    },
    {
      role: 'Tenant 1: Reviewer / Editor',
      name: 'Marcus Vance',
      email: 'reviewer@northstar.demo',
      pass: 'Northstar2026!',
      org: 'Northstar Digital',
      badge: 'Document Review & Verification'
    },
    {
      role: 'Tenant 1: Read-Only Viewer',
      name: 'Elena Rostova',
      email: 'viewer@northstar.demo',
      pass: 'Northstar2026!',
      org: 'Northstar Digital',
      badge: 'Governed Search & Citations'
    },
    {
      role: 'Tenant 2: Isolated Tenant Owner',
      name: 'Frank Reynolds',
      email: 'admin@acme.demo',
      pass: 'Acme2026!',
      org: 'Acme Aerospace (Tenant 2)',
      badge: 'Strict Cross-Tenant Isolation Proof'
    }
  ];

  const handleDemoLogin = async (userEmail: string, pass: string) => {
    setIsLoading(true);
    setError(null);
    try {
      const res = await api.login(userEmail, pass);
      onSuccess(res);
    } catch (err: any) {
      setError(err.message || 'Demo authentication failed.');
    } finally {
      setIsLoading(false);
    }
  };

  const handleSignIn = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!username || !password) {
      setError('Please provide both username/email and password.');
      return;
    }
    setIsLoading(true);
    setError(null);
    try {
      const res = await api.login(username, password);
      onSuccess(res);
    } catch (err: any) {
      setError(err.message || 'Invalid credentials.');
    } finally {
      setIsLoading(false);
    }
  };

  const handleRegister = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!username || !password) {
      setError('Please provide username and password.');
      return;
    }
    setIsLoading(true);
    setError(null);
    try {
      const res = await api.register(username, email, password, orgName || undefined);
      onSuccess({ user: res.user, organizations: [res.organization] });
    } catch (err: any) {
      setError(err.message || 'Registration failed.');
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div 
      className="fixed inset-0 z-50 flex items-center justify-center p-4 backdrop-blur-sm"
      style={{ backgroundColor: 'var(--modal-overlay)' }}
    >
      <div 
        className="rounded-2xl border w-full max-w-xl shadow-2xl overflow-hidden flex flex-col animate-in fade-in zoom-in-95 duration-150"
        style={{
          backgroundColor: 'var(--bg-surface)',
          borderColor: 'var(--border-color)',
        }}
      >
        {/* Header */}
        <div 
          className="p-6 border-b"
          style={{
            backgroundColor: 'var(--bg-surface)',
            borderColor: 'var(--border-color)',
          }}
        >
          <div className="flex items-center justify-between mb-2">
            <div className="flex items-center gap-3">
              <img 
                src="/logo.png" 
                alt="LORE Logo" 
                className="w-10 h-10 rounded-xl border object-contain p-0.5 shadow-sm"
                style={{
                  backgroundColor: 'var(--bg-surface-soft)',
                  borderColor: 'var(--border-color)',
                }}
              />
              <div>
                <h2 className="text-lg sm:text-xl font-bold tracking-tight flex items-center gap-2 text-[var(--text-primary)]">
                  LORE Enterprise
                  <span 
                    className="text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded border"
                    style={{
                      backgroundColor: 'var(--accent-light)',
                      borderColor: 'var(--border-color)',
                      color: 'var(--brand-accent)',
                    }}
                  >
                    SaaS Auth
                  </span>
                </h2>
                <p className="text-xs text-[var(--text-muted)]">Governed Multi-Tenant Knowledge Workspace</p>
              </div>
            </div>
            {onClose && (
              <button
                onClick={onClose}
                className="p-1.5 rounded-xl border transition cursor-pointer hover:border-[var(--brand-accent)]"
                style={{
                  backgroundColor: 'var(--bg-surface-soft)',
                  borderColor: 'var(--border-color)',
                  color: 'var(--text-muted)',
                }}
                title="Continue as Guest"
              >
                <X className="w-4 h-4" />
              </button>
            )}
          </div>

          {/* Mode Switcher */}
          <div 
            className="flex items-center gap-1.5 mt-4 p-1 rounded-xl border"
            style={{
              backgroundColor: 'var(--bg-surface-soft)',
              borderColor: 'var(--border-color)',
            }}
          >
            <button
              onClick={() => { setMode('demo'); setError(null); }}
              className="flex-1 py-1.5 text-xs font-semibold rounded-lg transition-all cursor-pointer"
              style={{
                backgroundColor: mode === 'demo' ? 'var(--brand-accent)' : 'transparent',
                color: mode === 'demo' ? 'var(--cta-text)' : 'var(--text-secondary)',
              }}
            >
              1-Click Demo Profiles
            </button>
            <button
              onClick={() => { setMode('signin'); setError(null); }}
              className="flex-1 py-1.5 text-xs font-semibold rounded-lg transition-all cursor-pointer"
              style={{
                backgroundColor: mode === 'signin' ? 'var(--brand-accent)' : 'transparent',
                color: mode === 'signin' ? 'var(--cta-text)' : 'var(--text-secondary)',
              }}
            >
              Sign In
            </button>
            <button
              onClick={() => { setMode('register'); setError(null); }}
              className="flex-1 py-1.5 text-xs font-semibold rounded-lg transition-all cursor-pointer"
              style={{
                backgroundColor: mode === 'register' ? 'var(--brand-accent)' : 'transparent',
                color: mode === 'register' ? 'var(--cta-text)' : 'var(--text-secondary)',
              }}
            >
              Register
            </button>
          </div>
        </div>

        {/* Content Area */}
        <div className="p-6 space-y-4 max-h-[70vh] overflow-y-auto">
          {error && (
            <div 
              className="p-3 rounded-xl border text-xs flex items-center gap-2"
              style={{
                backgroundColor: 'var(--error-bg)',
                borderColor: 'var(--border-color)',
                color: 'var(--error)',
              }}
            >
              <AlertCircle className="w-4 h-4 shrink-0" />
              <span>{error}</span>
            </div>
          )}

          {mode === 'demo' && (
            <div className="space-y-3">
              <div className="flex items-center justify-between text-xs text-[var(--text-muted)] pb-1">
                <span>Select a persona to test role-based access & isolation:</span>
                <span className="text-[11px] font-mono text-[var(--brand-accent)] font-semibold">Password: Northstar2026!</span>
              </div>

              <div className="grid grid-cols-1 gap-2.5">
                {demoAccounts.map((acc) => (
                  <button
                    key={acc.email}
                    disabled={isLoading}
                    onClick={() => handleDemoLogin(acc.email, acc.pass)}
                    className="flex items-center justify-between p-3.5 rounded-xl border text-left transition-all cursor-pointer group hover:scale-[1.01]"
                    style={{
                      backgroundColor: 'var(--bg-surface-soft)',
                      borderColor: 'var(--border-color)',
                    }}
                  >
                    <div>
                      <div className="flex items-center gap-2">
                        <span className="text-sm font-bold text-[var(--text-primary)] group-hover:text-[var(--brand-accent)] transition">
                          {acc.name}
                        </span>
                        <span 
                          className="text-[10px] px-2 py-0.5 rounded-full border font-semibold"
                          style={{
                            backgroundColor: 'var(--bg-surface)',
                            borderColor: 'var(--border-color)',
                            color: 'var(--text-muted)',
                          }}
                        >
                          {acc.role}
                        </span>
                      </div>
                      <div className="text-xs text-[var(--text-muted)] mt-1 flex items-center gap-2">
                        <span>{acc.org}</span>
                        <span>•</span>
                        <span className="text-[11px]">{acc.email}</span>
                      </div>
                      <div className="text-[11px] text-[var(--brand-accent)] mt-1 font-semibold">
                        {acc.badge}
                      </div>
                    </div>
                    <ArrowRight className="w-4 h-4 text-[var(--brand-accent)] opacity-70 group-hover:opacity-100 group-hover:translate-x-1 transition shrink-0" />
                  </button>
                ))}
              </div>

              {/* SSO Announcement */}
              <div 
                className="mt-4 p-3 rounded-xl border flex items-center gap-2.5 text-xs text-[var(--text-muted)]"
                style={{
                  backgroundColor: 'var(--bg-surface-soft)',
                  borderColor: 'var(--border-color)',
                }}
              >
                <Sparkles className="w-4 h-4 text-[var(--brand-accent)] shrink-0" />
                <span>
                  <strong>Google OAuth 2.0 SSO</strong> connector placeholder is ready; multi-tenant identity federation will link to this boundary.
                </span>
              </div>
            </div>
          )}

          {mode === 'signin' && (
            <form onSubmit={handleSignIn} className="space-y-4">
              <div>
                <label className="block text-xs font-semibold text-[var(--text-secondary)] mb-1">
                  Username or Email
                </label>
                <div className="relative">
                  <User className="w-4 h-4 text-[var(--text-muted)] absolute left-3 top-3" />
                  <input
                    type="text"
                    value={username}
                    onChange={(e) => setUsername(e.target.value)}
                    placeholder="admin@northstar.demo"
                    className="w-full border rounded-xl pl-9 pr-3 py-2 text-xs sm:text-sm focus:outline-none"
                    style={{
                      backgroundColor: 'var(--input-bg)',
                      borderColor: 'var(--input-border)',
                      color: 'var(--text-primary)',
                    }}
                    required
                  />
                </div>
              </div>

              <div>
                <label className="block text-xs font-semibold text-[var(--text-secondary)] mb-1">
                  Password
                </label>
                <div className="relative">
                  <Lock className="w-4 h-4 text-[var(--text-muted)] absolute left-3 top-3" />
                  <input
                    type="password"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    placeholder="••••••••••••"
                    className="w-full border rounded-xl pl-9 pr-3 py-2 text-xs sm:text-sm focus:outline-none"
                    style={{
                      backgroundColor: 'var(--input-bg)',
                      borderColor: 'var(--input-border)',
                      color: 'var(--text-primary)',
                    }}
                    required
                  />
                </div>
              </div>

              <button
                type="submit"
                disabled={isLoading}
                className="w-full py-2.5 rounded-xl font-semibold text-xs sm:text-sm shadow-sm transition flex items-center justify-center gap-2 cursor-pointer active:scale-95 disabled:opacity-50"
                style={{
                  backgroundColor: 'var(--brand-accent)',
                  color: 'var(--cta-text)',
                }}
              >
                {isLoading ? 'Signing In...' : 'Sign In to Workspace'}
                <ArrowRight className="w-4 h-4" />
              </button>
            </form>
          )}

          {mode === 'register' && (
            <form onSubmit={handleRegister} className="space-y-3.5">
              <div>
                <label className="block text-xs font-semibold text-[var(--text-secondary)] mb-1">
                  Organization / Company Name
                </label>
                <div className="relative">
                  <Building2 className="w-4 h-4 text-[var(--text-muted)] absolute left-3 top-3" />
                  <input
                    type="text"
                    value={orgName}
                    onChange={(e) => setOrgName(e.target.value)}
                    placeholder="Northstar Digital"
                    className="w-full border rounded-xl pl-9 pr-3 py-2 text-xs sm:text-sm focus:outline-none"
                    style={{
                      backgroundColor: 'var(--input-bg)',
                      borderColor: 'var(--input-border)',
                      color: 'var(--text-primary)',
                    }}
                    required
                  />
                </div>
              </div>

              <div>
                <label className="block text-xs font-semibold text-[var(--text-secondary)] mb-1">
                  Email Address
                </label>
                <input
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="sarah.chen@northstar.demo"
                  className="w-full border rounded-xl px-3 py-2 text-xs sm:text-sm focus:outline-none"
                  style={{
                    backgroundColor: 'var(--input-bg)',
                    borderColor: 'var(--input-border)',
                    color: 'var(--text-primary)',
                  }}
                />
              </div>

              <div>
                <label className="block text-xs font-semibold text-[var(--text-secondary)] mb-1">
                  Username
                </label>
                <input
                  type="text"
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  placeholder="sarah_admin"
                  className="w-full border rounded-xl px-3 py-2 text-xs sm:text-sm focus:outline-none"
                  style={{
                    backgroundColor: 'var(--input-bg)',
                    borderColor: 'var(--input-border)',
                    color: 'var(--text-primary)',
                  }}
                  required
                />
              </div>

              <div>
                <label className="block text-xs font-semibold text-[var(--text-secondary)] mb-1">
                  Password
                </label>
                <input
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="••••••••••••"
                  className="w-full border rounded-xl px-3 py-2 text-xs sm:text-sm focus:outline-none"
                  style={{
                    backgroundColor: 'var(--input-bg)',
                    borderColor: 'var(--input-border)',
                    color: 'var(--text-primary)',
                  }}
                  required
                />
              </div>

              <button
                type="submit"
                disabled={isLoading}
                className="w-full py-2.5 rounded-xl font-semibold text-xs sm:text-sm shadow-sm transition flex items-center justify-center gap-2 cursor-pointer active:scale-95 disabled:opacity-50 mt-2"
                style={{
                  backgroundColor: 'var(--brand-accent)',
                  color: 'var(--cta-text)',
                }}
              >
                {isLoading ? 'Creating Enterprise Account...' : 'Create Organization & Join'}
                <ArrowRight className="w-4 h-4" />
              </button>
            </form>
          )}
        </div>

        {/* Footer */}
        <div 
          className="p-4 border-t flex items-center justify-between text-[11px]"
          style={{
            backgroundColor: 'var(--bg-surface-soft)',
            borderColor: 'var(--border-color)',
            color: 'var(--text-muted)',
          }}
        >
          <div className="flex items-center gap-2">
            {onClose && (
              <button
                onClick={onClose}
                className="px-2.5 py-1 rounded-xl border text-xs font-semibold transition cursor-pointer flex items-center gap-1.5"
                style={{
                  backgroundColor: 'var(--bg-surface)',
                  borderColor: 'var(--border-color)',
                  color: 'var(--brand-accent)',
                }}
              >
                <span>Continue as Guest</span>
                <ArrowRight className="w-3.5 h-3.5" />
              </button>
            )}
            <span className="hidden sm:inline">Tenant Isolation Active</span>
          </div>
          <span className="flex items-center gap-1 text-[var(--success)] font-semibold">
            <CheckCircle2 className="w-3.5 h-3.5" />
            Zero Data Leakage
          </span>
        </div>
      </div>
    </div>
  );
};
