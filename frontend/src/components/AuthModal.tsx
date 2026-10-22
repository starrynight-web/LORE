'use client';

import React, { useState } from 'react';
import { 
  ShieldCheck, 
  Building2, 
  Lock, 
  User, 
  ArrowRight, 
  KeyRound, 
  Layers, 
  CheckCircle2, 
  AlertCircle,
  Sparkles,
  X
} from 'lucide-react';
import { api, User as UserType, Organization } from '@/lib/api';

interface AuthModalProps {
  onSuccess: (data: { user: UserType; organizations?: Organization[] }) => void;
  onClose?: () => void;
}

export const AuthModal: React.FC<AuthModalProps> = ({ onSuccess, onClose }) => {
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
      plan: 'Enterprise Scale',
      color: 'border-indigo-500/50 hover:border-indigo-500 bg-indigo-950/20 text-indigo-400',
      badge: 'Full Governance & Ingestion Control'
    },
    {
      role: 'Tenant 1: Reviewer / Editor',
      name: 'Marcus Vance',
      email: 'reviewer@northstar.demo',
      pass: 'Northstar2026!',
      org: 'Northstar Digital',
      plan: 'Enterprise Scale',
      color: 'border-amber-500/50 hover:border-amber-500 bg-amber-950/20 text-amber-400',
      badge: 'Document Review & Verification'
    },
    {
      role: 'Tenant 1: Read-Only Viewer',
      name: 'Elena Rostova',
      email: 'viewer@northstar.demo',
      pass: 'Northstar2026!',
      org: 'Northstar Digital',
      plan: 'Enterprise Scale',
      color: 'border-slate-500/50 hover:border-slate-500 bg-slate-900 text-slate-300',
      badge: 'Governed Search & Citations'
    },
    {
      role: 'Tenant 2: Isolated Tenant Owner',
      name: 'Frank Reynolds',
      email: 'admin@acme.demo',
      pass: 'Acme2026!',
      org: 'Acme Aerospace (Tenant 2)',
      plan: 'Starter Tier',
      color: 'border-rose-500/50 hover:border-rose-500 bg-rose-950/20 text-rose-400',
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
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/80 backdrop-blur-md p-4">
      <div className="bg-slate-900 border border-slate-800 rounded-2xl w-full max-w-xl shadow-2xl overflow-hidden flex flex-col">
        {/* Header */}
        <div className="p-6 bg-gradient-to-r from-slate-900 via-indigo-950/40 to-slate-900 border-b border-slate-800">
          <div className="flex items-center justify-between mb-2">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-xl bg-gradient-to-tr from-indigo-600 to-violet-500 flex items-center justify-center text-white shadow-lg shadow-indigo-600/30">
                <ShieldCheck className="w-5 h-5" />
              </div>
              <div>
                <h2 className="text-xl font-bold text-white tracking-tight flex items-center gap-2">
                  LORE Enterprise
                  <span className="text-[10px] font-semibold uppercase tracking-wider px-2 py-0.5 rounded bg-indigo-500/20 text-indigo-400 border border-indigo-500/30">
                    SaaS Auth
                  </span>
                </h2>
                <p className="text-xs text-slate-400">Governed Multi-Tenant Knowledge Workspace</p>
              </div>
            </div>
            {onClose && (
              <button
                onClick={onClose}
                className="p-1.5 rounded-lg text-slate-400 hover:text-white hover:bg-slate-800 transition cursor-pointer"
                title="Continue as Guest"
              >
                <X className="w-5 h-5" />
              </button>
            )}
          </div>

          {/* Mode Switcher */}
          <div className="flex items-center gap-2 mt-4 bg-slate-950/50 p-1 rounded-lg border border-slate-800">
            <button
              onClick={() => { setMode('demo'); setError(null); }}
              className={`flex-1 py-1.5 text-xs font-semibold rounded-md transition ${
                mode === 'demo'
                  ? 'bg-indigo-600 text-white shadow-sm'
                  : 'text-slate-400 hover:text-white'
              }`}
            >
              1-Click Demo Profiles
            </button>
            <button
              onClick={() => { setMode('signin'); setError(null); }}
              className={`flex-1 py-1.5 text-xs font-semibold rounded-md transition ${
                mode === 'signin'
                  ? 'bg-indigo-600 text-white shadow-sm'
                  : 'text-slate-400 hover:text-white'
              }`}
            >
              Sign In
            </button>
            <button
              onClick={() => { setMode('register'); setError(null); }}
              className={`flex-1 py-1.5 text-xs font-semibold rounded-md transition ${
                mode === 'register'
                  ? 'bg-indigo-600 text-white shadow-sm'
                  : 'text-slate-400 hover:text-white'
              }`}
            >
              Register
            </button>
          </div>
        </div>

        {/* Content Area */}
        <div className="p-6 space-y-4 max-h-[70vh] overflow-y-auto">
          {error && (
            <div className="p-3 rounded-lg bg-rose-500/10 border border-rose-500/30 flex items-center gap-2 text-xs text-rose-400">
              <AlertCircle className="w-4 h-4 shrink-0" />
              <span>{error}</span>
            </div>
          )}

          {mode === 'demo' && (
            <div className="space-y-3">
              <div className="flex items-center justify-between text-xs text-slate-400 pb-1">
                <span>Select a persona to test role-based access & tenant isolation:</span>
                <span className="text-[11px] text-indigo-400 font-mono">Password: Northstar2026!</span>
              </div>

              <div className="grid grid-cols-1 gap-2.5">
                {demoAccounts.map((acc) => (
                  <button
                    key={acc.email}
                    disabled={isLoading}
                    onClick={() => handleDemoLogin(acc.email, acc.pass)}
                    className={`flex items-center justify-between p-3.5 rounded-xl border text-left transition ${acc.color} cursor-pointer group hover:scale-[1.01]`}
                  >
                    <div>
                      <div className="flex items-center gap-2">
                        <span className="text-sm font-bold text-white group-hover:text-indigo-300 transition">
                          {acc.name}
                        </span>
                        <span className="text-[11px] px-2 py-0.5 rounded-full bg-slate-800/80 text-slate-300 border border-slate-700/60 font-medium">
                          {acc.role}
                        </span>
                      </div>
                      <div className="text-xs text-slate-400 mt-1 flex items-center gap-2">
                        <span>{acc.org}</span>
                        <span>•</span>
                        <span className="text-[11px] text-slate-400">{acc.email}</span>
                      </div>
                      <div className="text-[11px] text-indigo-400 mt-1 font-medium">
                        {acc.badge}
                      </div>
                    </div>
                    <ArrowRight className="w-4 h-4 opacity-70 group-hover:opacity-100 group-hover:translate-x-1 transition shrink-0" />
                  </button>
                ))}
              </div>

              {/* SSO Announcement */}
              <div className="mt-4 p-3 rounded-lg bg-slate-800/40 border border-slate-700/40 flex items-center gap-2.5 text-xs text-slate-400">
                <Sparkles className="w-4 h-4 text-violet-400 shrink-0" />
                <span>
                  <strong>Google OAuth 2.0 SSO</strong> connector placeholder is ready; multi-tenant identity federation will link to this boundary.
                </span>
              </div>
            </div>
          )}

          {mode === 'signin' && (
            <form onSubmit={handleSignIn} className="space-y-4">
              <div>
                <label className="block text-xs font-medium text-slate-300 mb-1">
                  Username or Email
                </label>
                <div className="relative">
                  <User className="w-4 h-4 text-slate-500 absolute left-3 top-3" />
                  <input
                    type="text"
                    value={username}
                    onChange={(e) => setUsername(e.target.value)}
                    placeholder="admin@northstar.demo"
                    className="w-full bg-slate-800 border border-slate-700 rounded-lg pl-9 pr-3 py-2 text-sm text-white focus:outline-none focus:border-indigo-500"
                    required
                  />
                </div>
              </div>

              <div>
                <label className="block text-xs font-medium text-slate-300 mb-1">
                  Password
                </label>
                <div className="relative">
                  <Lock className="w-4 h-4 text-slate-500 absolute left-3 top-3" />
                  <input
                    type="password"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    placeholder="••••••••••••"
                    className="w-full bg-slate-800 border border-slate-700 rounded-lg pl-9 pr-3 py-2 text-sm text-white focus:outline-none focus:border-indigo-500"
                    required
                  />
                </div>
              </div>

              <button
                type="submit"
                disabled={isLoading}
                className="w-full py-2.5 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white font-semibold text-sm shadow-md shadow-indigo-600/30 transition flex items-center justify-center gap-2 cursor-pointer"
              >
                {isLoading ? 'Signing In...' : 'Sign In to Workspace'}
                <ArrowRight className="w-4 h-4" />
              </button>
            </form>
          )}

          {mode === 'register' && (
            <form onSubmit={handleRegister} className="space-y-3.5">
              <div>
                <label className="block text-xs font-medium text-slate-300 mb-1">
                  Organization / Company Name
                </label>
                <div className="relative">
                  <Building2 className="w-4 h-4 text-slate-500 absolute left-3 top-3" />
                  <input
                    type="text"
                    value={orgName}
                    onChange={(e) => setOrgName(e.target.value)}
                    placeholder="Northstar Digital"
                    className="w-full bg-slate-800 border border-slate-700 rounded-lg pl-9 pr-3 py-2 text-sm text-white focus:outline-none focus:border-indigo-500"
                    required
                  />
                </div>
              </div>

              <div>
                <label className="block text-xs font-medium text-slate-300 mb-1">
                  Email Address
                </label>
                <input
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="sarah.chen@northstar.demo"
                  className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-indigo-500"
                />
              </div>

              <div>
                <label className="block text-xs font-medium text-slate-300 mb-1">
                  Username
                </label>
                <input
                  type="text"
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  placeholder="sarah_admin"
                  className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-indigo-500"
                  required
                />
              </div>

              <div>
                <label className="block text-xs font-medium text-slate-300 mb-1">
                  Password
                </label>
                <input
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="••••••••••••"
                  className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-indigo-500"
                  required
                />
              </div>

              <button
                type="submit"
                disabled={isLoading}
                className="w-full py-2.5 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white font-semibold text-sm shadow-md shadow-indigo-600/30 transition flex items-center justify-center gap-2 cursor-pointer mt-2"
              >
                {isLoading ? 'Creating Enterprise Account...' : 'Create Organization & Join'}
                <ArrowRight className="w-4 h-4" />
              </button>
            </form>
          )}
        </div>

        {/* Footer */}
        <div className="p-4 bg-slate-950/60 border-t border-slate-800 flex items-center justify-between text-[11px] text-slate-400">
          <div className="flex items-center gap-2">
            {onClose && (
              <button
                onClick={onClose}
                className="px-2.5 py-1 rounded bg-slate-800 hover:bg-slate-700 text-indigo-300 hover:text-white text-xs font-semibold transition cursor-pointer flex items-center gap-1.5"
              >
                <span>Continue as Guest</span>
                <ArrowRight className="w-3.5 h-3.5" />
              </button>
            )}
            <span className="hidden sm:inline">Tenant Isolation Active</span>
          </div>
          <span className="text-emerald-400 flex items-center gap-1">
            <CheckCircle2 className="w-3.5 h-3.5" />
            Zero Data Leakage
          </span>
        </div>
      </div>
    </div>
  );
};
