'use client';

import React, { useState, useEffect } from 'react';
import { 
  Building2, 
  Users, 
  CreditCard, 
  ShieldCheck, 
  UserPlus, 
  Trash2, 
  Check, 
  Copy, 
  Sparkles, 
  HardDrive, 
  FileText, 
  Search, 
  AlertCircle,
  Crown,
  Palette,
  Globe
} from 'lucide-react';
import { 
  api, 
  Organization, 
  Plan, 
  SubscriptionData, 
  OrganizationMember, 
  OrganizationInvitation 
} from '@/lib/api';
import { useI18n } from '@/lib/i18n';
import { ThemeToggle, LanguageToggle } from '@/components/PremiumToggles';

interface OrgSettingsProps {
  currentOrg: Organization | null;
  userRole?: string;
  onRefreshOrg?: () => void;
}

export const OrganizationSettingsView: React.FC<OrgSettingsProps> = ({
  currentOrg,
  userRole = 'member',
  onRefreshOrg
}) => {
  const { t } = useI18n();
  const [plans, setPlans] = useState<Plan[]>([]);
  const [subData, setSubData] = useState<SubscriptionData | null>(null);
  const [members, setMembers] = useState<OrganizationMember[]>([]);
  const [invitations, setInvitations] = useState<OrganizationInvitation[]>([]);
  const [inviteEmail, setInviteEmail] = useState('');
  const [inviteRole, setInviteRole] = useState('member');
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [copiedToken, setCopiedToken] = useState<string | null>(null);

  const isOwnerOrAdmin = userRole === 'owner' || userRole === 'admin';

  const loadData = async () => {
    if (!currentOrg) return;
    try {
      const [pList, sData, mList, iList] = await Promise.all([
        api.getPlans().catch(() => []),
        api.getSubscription(currentOrg.id).catch(() => null),
        api.getOrgMembers(currentOrg.id).catch(() => []),
        api.getOrgInvitations(currentOrg.id).catch(() => [])
      ]);
      setPlans(pList);
      setSubData(sData);
      setMembers(mList);
      setInvitations(iList);
    } catch (e: any) {
      console.error("Failed loading org settings:", e);
    }
  };

  useEffect(() => {
    loadData();
  }, [currentOrg?.id]);

  const handleCreateInvite = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!currentOrg || !inviteEmail) return;
    setError(null);
    setMessage(null);
    try {
      const inv = await api.createOrgInvitation(currentOrg.id, inviteEmail, inviteRole);
      setInvitations([inv, ...invitations]);
      setInviteEmail('');
      setMessage(`Invitation created for ${inv.email}`);
    } catch (e: any) {
      setError(e.message || 'Failed to create invitation.');
    }
  };

  const handleRemoveMember = async (membershipId: string) => {
    if (!currentOrg || !confirm("Are you sure you want to remove this member?")) return;
    try {
      await api.removeOrgMember(currentOrg.id, membershipId);
      setMembers(members.filter(m => m.id !== membershipId));
      setMessage("Member removed.");
    } catch (e: any) {
      setError(e.message || 'Failed to remove member.');
    }
  };

  const handleChangePlan = async (planSlug: string) => {
    if (!currentOrg) return;
    setError(null);
    setMessage(null);
    try {
      await api.changePlan(currentOrg.id, planSlug);
      setMessage(`Plan updated to ${planSlug}!`);
      await loadData();
    } catch (e: any) {
      setError(e.message || 'Failed to change plan.');
    }
  };

  const copyToClipboard = (token: string) => {
    navigator.clipboard.writeText(token);
    setCopiedToken(token);
    setTimeout(() => setCopiedToken(null), 2000);
  };

  if (!currentOrg) {
    return (
      <div className="p-8 text-center text-[var(--text-muted)] text-sm">
        Please select an active organization to manage settings.
      </div>
    );
  }

  const currentPlanSlug = subData?.subscription?.plan?.slug || 'starter';
  const usage = subData?.usage;
  const quotas = subData?.quotas;

  return (
    <div className="max-w-6xl mx-auto space-y-6">
      {/* Top Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div>
          <h1 className="text-xl sm:text-2xl font-extrabold text-[var(--text-primary)] tracking-tight flex items-center gap-3">
            <Building2 className="w-6 h-6 text-[var(--brand-accent)]" />
            <span>{currentOrg.name}</span>
          </h1>
          <p className="text-xs sm:text-sm text-[var(--text-muted)] mt-1">
            Enterprise SaaS Control Plane • Role: <span className="font-bold text-[var(--brand-accent)] capitalize">{userRole}</span>
          </p>
        </div>

        <div className="flex items-center gap-2">
          <span 
            className="px-3 py-1 rounded-full text-xs font-semibold border flex items-center gap-1.5"
            style={{
              backgroundColor: 'var(--accent-light)',
              borderColor: 'var(--border-color)',
              color: 'var(--brand-accent)',
            }}
          >
            <ShieldCheck className="w-3.5 h-3.5" />
            Active SaaS Tenant
          </span>
        </div>
      </div>

      {message && (
        <div 
          className="p-3.5 rounded-xl border flex items-center gap-2 text-xs"
          style={{
            backgroundColor: 'var(--success-bg)',
            borderColor: 'var(--border-color)',
            color: 'var(--success)',
          }}
        >
          <Check className="w-4 h-4 shrink-0" />
          <span>{message}</span>
        </div>
      )}

      {error && (
        <div 
          className="p-3.5 rounded-xl border flex items-center gap-2 text-xs"
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

      {/* Appearance & Localization Section (Master Prompt 11.K) */}
      <div 
        className="p-6 rounded-2xl border shadow-sm space-y-4"
        style={{
          backgroundColor: 'var(--bg-surface)',
          borderColor: 'var(--border-color)',
        }}
      >
        <div className="border-b pb-3" style={{ borderColor: 'var(--border-color)' }}>
          <h2 className="text-sm sm:text-base font-bold text-[var(--text-primary)] flex items-center gap-2">
            <Palette className="w-4 h-4 text-[var(--brand-accent)]" />
            <span>{t('settings.theme_section')} & {t('settings.lang_section')}</span>
          </h2>
          <p className="text-xs text-[var(--text-muted)] mt-0.5">
            Synchronize your workspace appearance and language preferences across the platform.
          </p>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {/* Theme Card */}
          <div 
            className="p-4 rounded-xl border flex items-center justify-between"
            style={{
              backgroundColor: 'var(--bg-surface-soft)',
              borderColor: 'var(--border-color)',
            }}
          >
            <div>
              <div className="text-xs font-bold text-[var(--text-primary)]">{t('settings.theme_desc')}</div>
              <div className="text-[11px] text-[var(--text-muted)] mt-0.5">
                Light (Parrot & Cream) ↔ Dark (Obsidian & Emerald)
              </div>
            </div>
            <ThemeToggle />
          </div>

          {/* Language Card */}
          <div 
            className="p-4 rounded-xl border flex items-center justify-between"
            style={{
              backgroundColor: 'var(--bg-surface-soft)',
              borderColor: 'var(--border-color)',
            }}
          >
            <div>
              <div className="text-xs font-bold text-[var(--text-primary)]">{t('settings.lang_desc')}</div>
              <div className="text-[11px] text-[var(--text-muted)] mt-0.5">
                বাংলা (Bengali) ↔ English (EN)
              </div>
            </div>
            <LanguageToggle />
          </div>
        </div>
      </div>

      {/* Quota Usage Meters */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <div 
          className="p-5 rounded-2xl border shadow-sm"
          style={{
            backgroundColor: 'var(--bg-surface)',
            borderColor: 'var(--border-color)',
          }}
        >
          <div className="flex items-center justify-between text-[var(--text-muted)] mb-2">
            <span className="text-xs font-bold uppercase tracking-wider flex items-center gap-1.5">
              <HardDrive className="w-4 h-4 text-[var(--brand-accent)]" /> Storage Consumption
            </span>
            <span className="text-xs font-mono text-[var(--text-primary)]">{usage?.storage_mb || 0} MB / {quotas?.max_storage_mb || 500} MB</span>
          </div>
          <div 
            className="w-full rounded-full h-2 overflow-hidden"
            style={{ backgroundColor: 'var(--bg-surface-soft)' }}
          >
            <div 
              className="h-2 rounded-full transition-all duration-500"
              style={{ 
                backgroundColor: 'var(--brand-accent)',
                width: `${Math.min(100, ((usage?.storage_mb || 0) / (quotas?.max_storage_mb || 500)) * 100)}%` 
              }}
            />
          </div>
        </div>

        <div 
          className="p-5 rounded-2xl border shadow-sm"
          style={{
            backgroundColor: 'var(--bg-surface)',
            borderColor: 'var(--border-color)',
          }}
        >
          <div className="flex items-center justify-between text-[var(--text-muted)] mb-2">
            <span className="text-xs font-bold uppercase tracking-wider flex items-center gap-1.5">
              <FileText className="w-4 h-4 text-[var(--brand-accent)]" /> Uploaded Documents
            </span>
            <span className="text-xs font-mono text-[var(--text-primary)]">{usage?.documents_count || 0} / {quotas?.max_documents || 50}</span>
          </div>
          <div 
            className="w-full rounded-full h-2 overflow-hidden"
            style={{ backgroundColor: 'var(--bg-surface-soft)' }}
          >
            <div 
              className="h-2 rounded-full transition-all duration-500"
              style={{ 
                backgroundColor: 'var(--brand-accent)',
                width: `${Math.min(100, ((usage?.documents_count || 0) / (quotas?.max_documents || 50)) * 100)}%` 
              }}
            />
          </div>
        </div>

        <div 
          className="p-5 rounded-2xl border shadow-sm"
          style={{
            backgroundColor: 'var(--bg-surface)',
            borderColor: 'var(--border-color)',
          }}
        >
          <div className="flex items-center justify-between text-[var(--text-muted)] mb-2">
            <span className="text-xs font-bold uppercase tracking-wider flex items-center gap-1.5">
              <Search className="w-4 h-4 text-[var(--brand-accent)]" /> Monthly Queries
            </span>
            <span className="text-xs font-mono text-[var(--text-primary)]">{usage?.queries_count || 0} / {quotas?.max_monthly_queries || 500}</span>
          </div>
          <div 
            className="w-full rounded-full h-2 overflow-hidden"
            style={{ backgroundColor: 'var(--bg-surface-soft)' }}
          >
            <div 
              className="h-2 rounded-full transition-all duration-500"
              style={{ 
                backgroundColor: 'var(--brand-accent)',
                width: `${Math.min(100, ((usage?.queries_count || 0) / (quotas?.max_monthly_queries || 500)) * 100)}%` 
              }}
            />
          </div>
        </div>
      </div>

      {/* Subscription Plans Section */}
      <div 
        className="p-6 rounded-2xl border shadow-sm space-y-4"
        style={{
          backgroundColor: 'var(--bg-surface)',
          borderColor: 'var(--border-color)',
        }}
      >
        <div className="flex items-center justify-between border-b pb-3" style={{ borderColor: 'var(--border-color)' }}>
          <div>
            <h2 className="text-sm sm:text-base font-bold text-[var(--text-primary)] flex items-center gap-2">
              <CreditCard className="w-4 h-4 text-[var(--brand-accent)]" />
              <span>Subscription & Plan Entitlements</span>
            </h2>
            <p className="text-xs text-[var(--text-muted)] mt-0.5">
              Provider: <span className="font-mono text-[var(--brand-accent)]">LocalDev / Stripe SaaS Adapter</span>
            </p>
          </div>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4 pt-1">
          {plans.map((p) => {
            const isCurrent = currentPlanSlug === p.slug;
            return (
              <div 
                key={p.id}
                className="p-5 rounded-2xl border flex flex-col justify-between transition-all"
                style={{
                  backgroundColor: isCurrent ? 'var(--accent-light)' : 'var(--bg-surface-soft)',
                  borderColor: isCurrent ? 'var(--brand-accent)' : 'var(--border-color)',
                }}
              >
                <div>
                  <div className="flex items-center justify-between">
                    <h3 className="text-base font-bold text-[var(--text-primary)] flex items-center gap-1.5">
                      {p.name}
                      {isCurrent && (
                        <span 
                          className="text-[10px] uppercase font-bold px-2 py-0.5 rounded-full border"
                          style={{
                            backgroundColor: 'var(--accent-light)',
                            borderColor: 'var(--border-color)',
                            color: 'var(--brand-accent)',
                          }}
                        >
                          Active Plan
                        </span>
                      )}
                    </h3>
                    <div className="text-right">
                      <span className="text-lg font-extrabold text-[var(--text-primary)]">${p.price_monthly}</span>
                      <span className="text-xs text-[var(--text-muted)]">/mo</span>
                    </div>
                  </div>
                  <p className="text-xs text-[var(--text-muted)] mt-2">{p.description}</p>

                  <ul className="mt-4 space-y-1.5 text-xs text-[var(--text-secondary)]">
                    <li className="flex items-center gap-2">
                      <Check className="w-3.5 h-3.5 text-[var(--brand-accent)]" /> Up to {p.max_storage_mb} MB Storage
                    </li>
                    <li className="flex items-center gap-2">
                      <Check className="w-3.5 h-3.5 text-[var(--brand-accent)]" /> {p.max_documents} Documents Indexed
                    </li>
                    <li className="flex items-center gap-2">
                      <Check className="w-3.5 h-3.5 text-[var(--brand-accent)]" /> {p.max_monthly_queries} Queries / month
                    </li>
                    <li className="flex items-center gap-2">
                      <Check className="w-3.5 h-3.5 text-[var(--brand-accent)]" /> {p.max_workspaces} Workspaces & {p.max_members} Members
                    </li>
                    {p.allow_custom_models && (
                      <li className="flex items-center gap-2 text-[var(--brand-accent)] font-semibold">
                        <Sparkles className="w-3.5 h-3.5" /> Real Local Embeddings + Qdrant Vectors
                      </li>
                    )}
                  </ul>
                </div>

                <div className="mt-6">
                  {isCurrent ? (
                    <button 
                      disabled 
                      className="w-full py-2 rounded-xl text-xs font-semibold cursor-default border"
                      style={{
                        backgroundColor: 'var(--bg-surface)',
                        borderColor: 'var(--border-color)',
                        color: 'var(--text-muted)',
                      }}
                    >
                      Current Plan
                    </button>
                  ) : (
                    <button
                      disabled={!isOwnerOrAdmin}
                      onClick={() => handleChangePlan(p.slug)}
                      className="w-full py-2 rounded-xl text-xs font-semibold transition cursor-pointer shadow-sm active:scale-95 disabled:opacity-40"
                      style={{
                        backgroundColor: 'var(--brand-accent)',
                        color: 'var(--cta-text)',
                      }}
                    >
                      {isOwnerOrAdmin ? `Switch to ${p.name}` : 'Owner/Admin Permission Required'}
                    </button>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* Member Management & Invitations */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {/* Members List */}
        <div 
          className="p-6 rounded-2xl border shadow-sm space-y-4"
          style={{
            backgroundColor: 'var(--bg-surface)',
            borderColor: 'var(--border-color)',
          }}
        >
          <div className="flex items-center justify-between border-b pb-3" style={{ borderColor: 'var(--border-color)' }}>
            <h2 className="text-sm sm:text-base font-bold text-[var(--text-primary)] flex items-center gap-2">
              <Users className="w-4 h-4 text-[var(--brand-accent)]" />
              <span>Active Team Members ({members.length})</span>
            </h2>
          </div>

          <div className="divide-y max-h-72 overflow-y-auto" style={{ borderColor: 'var(--border-color)' }}>
            {members.map((m) => (
              <div key={m.id} className="py-3 flex items-center justify-between">
                <div>
                  <div className="text-sm font-semibold text-[var(--text-primary)] flex items-center gap-2">
                    {m.user.first_name ? `${m.user.first_name} ${m.user.last_name}` : m.user.username}
                    {m.role === 'owner' && (
                      <Crown className="w-3.5 h-3.5 text-[var(--warning)]" />
                    )}
                  </div>
                  <div className="text-xs text-[var(--text-muted)]">
                    {m.user.email || m.user.username} • <span className="capitalize text-[var(--brand-accent)] font-semibold">{m.role}</span>
                  </div>
                </div>

                {isOwnerOrAdmin && m.role !== 'owner' && (
                  <button
                    onClick={() => handleRemoveMember(m.id)}
                    className="p-1.5 rounded-xl border text-[var(--text-muted)] hover:text-red-500 transition cursor-pointer"
                    style={{
                      backgroundColor: 'var(--bg-surface-soft)',
                      borderColor: 'var(--border-color)',
                    }}
                    title="Remove Member"
                  >
                    <Trash2 className="w-4 h-4" />
                  </button>
                )}
              </div>
            ))}
          </div>
        </div>

        {/* Invite New Member */}
        <div 
          className="p-6 rounded-2xl border shadow-sm space-y-4"
          style={{
            backgroundColor: 'var(--bg-surface)',
            borderColor: 'var(--border-color)',
          }}
        >
          <div className="flex items-center justify-between border-b pb-3" style={{ borderColor: 'var(--border-color)' }}>
            <h2 className="text-sm sm:text-base font-bold text-[var(--text-primary)] flex items-center gap-2">
              <UserPlus className="w-4 h-4 text-[var(--brand-accent)]" />
              <span>Invite Team Member</span>
            </h2>
          </div>

          {isOwnerOrAdmin ? (
            <form onSubmit={handleCreateInvite} className="space-y-3">
              <div>
                <label className="block text-xs font-semibold text-[var(--text-secondary)] mb-1">
                  Recipient Email
                </label>
                <input
                  type="email"
                  value={inviteEmail}
                  onChange={(e) => setInviteEmail(e.target.value)}
                  placeholder="colleague@enterprise.com"
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
                  Role Assignment
                </label>
                <select
                  value={inviteRole}
                  onChange={(e) => setInviteRole(e.target.value)}
                  className="w-full border rounded-xl px-3 py-2 text-xs sm:text-sm focus:outline-none cursor-pointer"
                  style={{
                    backgroundColor: 'var(--input-bg)',
                    borderColor: 'var(--input-border)',
                    color: 'var(--text-primary)',
                  }}
                >
                  <option value="member">Member (Read & Query Knowledge)</option>
                  <option value="editor">Editor (Upload & Manage Documents)</option>
                  <option value="admin">Administrator (Manage Settings & Policies)</option>
                </select>
              </div>

              <button
                type="submit"
                className="w-full py-2.5 rounded-xl font-semibold text-xs shadow-sm transition flex items-center justify-center gap-2 cursor-pointer active:scale-95"
                style={{
                  backgroundColor: 'var(--brand-accent)',
                  color: 'var(--cta-text)',
                }}
              >
                <UserPlus className="w-4 h-4" />
                <span>Generate Enterprise Invitation</span>
              </button>
            </form>
          ) : (
            <p className="text-xs text-[var(--text-muted)]">
              Only organization owners and administrators can invite new members.
            </p>
          )}

          {/* Pending Invitations list */}
          {invitations.length > 0 && (
            <div className="pt-2 border-t" style={{ borderColor: 'var(--border-color)' }}>
              <h3 className="text-xs font-bold uppercase tracking-wider text-[var(--text-muted)] mb-2">
                Pending Invitations ({invitations.length})
              </h3>
              <div className="space-y-2 max-h-40 overflow-y-auto">
                {invitations.map((inv) => (
                  <div 
                    key={inv.id} 
                    className="p-2.5 rounded-xl border flex items-center justify-between text-xs"
                    style={{
                      backgroundColor: 'var(--bg-surface-soft)',
                      borderColor: 'var(--border-color)',
                    }}
                  >
                    <div>
                      <div className="font-semibold text-[var(--text-primary)]">{inv.email}</div>
                      <div className="text-[11px] text-[var(--text-muted)]">
                        Role: <span className="text-[var(--brand-accent)] capitalize font-semibold">{inv.role}</span> • {inv.is_accepted ? 'Accepted' : 'Pending'}
                      </div>
                    </div>
                    <button
                      onClick={() => copyToClipboard(inv.token)}
                      className="flex items-center gap-1 px-2.5 py-1 rounded-lg border text-[11px] font-semibold transition cursor-pointer"
                      style={{
                        backgroundColor: 'var(--bg-surface)',
                        borderColor: 'var(--border-color)',
                        color: 'var(--text-secondary)',
                      }}
                    >
                      {copiedToken === inv.token ? <Check className="w-3 h-3 text-[var(--success)]" /> : <Copy className="w-3 h-3" />}
                      <span>{copiedToken === inv.token ? 'Copied' : 'Copy Token'}</span>
                    </button>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
