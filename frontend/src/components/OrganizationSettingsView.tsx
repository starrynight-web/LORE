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
  ExternalLink,
  Crown
} from 'lucide-react';
import { 
  api, 
  Organization, 
  Plan, 
  SubscriptionData, 
  OrganizationMember, 
  OrganizationInvitation 
} from '@/lib/api';

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
  const [plans, setPlans] = useState<Plan[]>([]);
  const [subData, setSubData] = useState<SubscriptionData | null>(null);
  const [members, setMembers] = useState<OrganizationMember[]>([]);
  const [invitations, setInvitations] = useState<OrganizationInvitation[]>([]);
  const [inviteEmail, setInviteEmail] = useState('');
  const [inviteRole, setInviteRole] = useState('member');
  const [isLoading, setIsLoading] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [copiedToken, setCopiedToken] = useState<string | null>(null);

  const isOwnerOrAdmin = userRole === 'owner' || userRole === 'admin';

  const loadData = async () => {
    if (!currentOrg) return;
    setIsLoading(true);
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
    } finally {
      setIsLoading(false);
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
      const res = await api.changePlan(currentOrg.id, planSlug);
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
      <div className="p-8 text-center text-slate-400">
        Please select an active organization to manage settings.
      </div>
    );
  }

  const currentPlanSlug = subData?.subscription?.plan?.slug || 'starter';
  const usage = subData?.usage;
  const quotas = subData?.quotas;

  return (
    <div className="p-8 max-w-6xl mx-auto space-y-8">
      {/* Top Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white tracking-tight flex items-center gap-3">
            <Building2 className="w-6 h-6 text-indigo-400" />
            <span>{currentOrg.name}</span>
          </h1>
          <p className="text-sm text-slate-400 mt-1">
            Enterprise SaaS Control Plane • Role: <span className="font-semibold text-indigo-400 capitalize">{userRole}</span>
          </p>
        </div>

        <div className="flex items-center gap-2">
          <span className="px-3 py-1 rounded-full text-xs font-semibold bg-emerald-500/20 text-emerald-400 border border-emerald-500/30 flex items-center gap-1.5">
            <ShieldCheck className="w-3.5 h-3.5" />
            Active SaaS Tenant
          </span>
        </div>
      </div>

      {message && (
        <div className="p-3.5 rounded-xl bg-emerald-500/10 border border-emerald-500/30 flex items-center gap-2 text-xs text-emerald-400">
          <Check className="w-4 h-4 shrink-0" />
          <span>{message}</span>
        </div>
      )}

      {error && (
        <div className="p-3.5 rounded-xl bg-rose-500/10 border border-rose-500/30 flex items-center gap-2 text-xs text-rose-400">
          <AlertCircle className="w-4 h-4 shrink-0" />
          <span>{error}</span>
        </div>
      )}

      {/* Quota Usage Meters */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <div className="p-5 rounded-2xl bg-slate-900 border border-slate-800">
          <div className="flex items-center justify-between text-slate-400 mb-2">
            <span className="text-xs font-semibold uppercase tracking-wider flex items-center gap-1.5">
              <HardDrive className="w-4 h-4 text-indigo-400" /> Storage Consumption
            </span>
            <span className="text-xs font-mono">{usage?.storage_mb || 0} MB / {quotas?.max_storage_mb || 500} MB</span>
          </div>
          <div className="w-full bg-slate-800 rounded-full h-2 overflow-hidden">
            <div 
              className="bg-indigo-500 h-2 rounded-full transition-all duration-500"
              style={{ width: `${Math.min(100, ((usage?.storage_mb || 0) / (quotas?.max_storage_mb || 500)) * 100)}%` }}
            />
          </div>
        </div>

        <div className="p-5 rounded-2xl bg-slate-900 border border-slate-800">
          <div className="flex items-center justify-between text-slate-400 mb-2">
            <span className="text-xs font-semibold uppercase tracking-wider flex items-center gap-1.5">
              <FileText className="w-4 h-4 text-violet-400" /> Uploaded Documents
            </span>
            <span className="text-xs font-mono">{usage?.documents_count || 0} / {quotas?.max_documents || 50}</span>
          </div>
          <div className="w-full bg-slate-800 rounded-full h-2 overflow-hidden">
            <div 
              className="bg-violet-500 h-2 rounded-full transition-all duration-500"
              style={{ width: `${Math.min(100, ((usage?.documents_count || 0) / (quotas?.max_documents || 50)) * 100)}%` }}
            />
          </div>
        </div>

        <div className="p-5 rounded-2xl bg-slate-900 border border-slate-800">
          <div className="flex items-center justify-between text-slate-400 mb-2">
            <span className="text-xs font-semibold uppercase tracking-wider flex items-center gap-1.5">
              <Search className="w-4 h-4 text-emerald-400" /> Monthly Queries
            </span>
            <span className="text-xs font-mono">{usage?.queries_count || 0} / {quotas?.max_monthly_queries || 500}</span>
          </div>
          <div className="w-full bg-slate-800 rounded-full h-2 overflow-hidden">
            <div 
              className="bg-emerald-500 h-2 rounded-full transition-all duration-500"
              style={{ width: `${Math.min(100, ((usage?.queries_count || 0) / (quotas?.max_monthly_queries || 500)) * 100)}%` }}
            />
          </div>
        </div>
      </div>

      {/* Subscription Plans Section */}
      <div className="p-6 rounded-2xl bg-slate-900 border border-slate-800 space-y-4">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-base font-bold text-white flex items-center gap-2">
              <CreditCard className="w-5 h-5 text-indigo-400" />
              Subscription & Plan Entitlements
            </h2>
            <p className="text-xs text-slate-400">
              Provider: <span className="font-mono text-indigo-300">LocalDev / Stripe Adapter</span>
            </p>
          </div>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4 pt-2">
          {plans.map((p) => {
            const isCurrent = currentPlanSlug === p.slug;
            return (
              <div 
                key={p.id}
                className={`p-5 rounded-xl border flex flex-col justify-between transition ${
                  isCurrent 
                    ? 'border-indigo-500/80 bg-indigo-950/20 shadow-lg shadow-indigo-500/10' 
                    : 'border-slate-800 bg-slate-950/40 hover:border-slate-700'
                }`}
              >
                <div>
                  <div className="flex items-center justify-between">
                    <h3 className="text-base font-bold text-white flex items-center gap-1.5">
                      {p.name}
                      {isCurrent && (
                        <span className="text-[10px] uppercase font-bold px-2 py-0.5 rounded-full bg-indigo-500/20 text-indigo-400 border border-indigo-500/30">
                          Active Plan
                        </span>
                      )}
                    </h3>
                    <div className="text-right">
                      <span className="text-lg font-bold text-white">${p.price_monthly}</span>
                      <span className="text-xs text-slate-400">/mo</span>
                    </div>
                  </div>
                  <p className="text-xs text-slate-400 mt-2">{p.description}</p>

                  <ul className="mt-4 space-y-1.5 text-xs text-slate-300">
                    <li className="flex items-center gap-2">
                      <Check className="w-3.5 h-3.5 text-indigo-400" /> Up to {p.max_storage_mb} MB Storage
                    </li>
                    <li className="flex items-center gap-2">
                      <Check className="w-3.5 h-3.5 text-indigo-400" /> {p.max_documents} Documents Indexed
                    </li>
                    <li className="flex items-center gap-2">
                      <Check className="w-3.5 h-3.5 text-indigo-400" /> {p.max_monthly_queries} Queries / month
                    </li>
                    <li className="flex items-center gap-2">
                      <Check className="w-3.5 h-3.5 text-indigo-400" /> {p.max_workspaces} Workspaces & {p.max_members} Members
                    </li>
                    {p.allow_custom_models && (
                      <li className="flex items-center gap-2 text-violet-400 font-medium">
                        <Sparkles className="w-3.5 h-3.5" /> Real Local Embeddings + Qdrant Vectors
                      </li>
                    )}
                  </ul>
                </div>

                <div className="mt-6">
                  {isCurrent ? (
                    <button 
                      disabled 
                      className="w-full py-2 rounded-lg bg-slate-800 text-slate-400 text-xs font-semibold cursor-default"
                    >
                      Current Plan
                    </button>
                  ) : (
                    <button
                      disabled={!isOwnerOrAdmin}
                      onClick={() => handleChangePlan(p.slug)}
                      className={`w-full py-2 rounded-lg text-xs font-semibold transition cursor-pointer ${
                        isOwnerOrAdmin 
                          ? 'bg-indigo-600 hover:bg-indigo-500 text-white shadow-md shadow-indigo-600/30' 
                          : 'bg-slate-800 text-slate-500 cursor-not-allowed'
                      }`}
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
        <div className="p-6 rounded-2xl bg-slate-900 border border-slate-800 space-y-4">
          <div className="flex items-center justify-between">
            <h2 className="text-base font-bold text-white flex items-center gap-2">
              <Users className="w-5 h-5 text-indigo-400" />
              Active Team Members ({members.length})
            </h2>
          </div>

          <div className="divide-y divide-slate-800 max-h-72 overflow-y-auto">
            {members.map((m) => (
              <div key={m.id} className="py-3 flex items-center justify-between">
                <div>
                  <div className="text-sm font-semibold text-white flex items-center gap-2">
                    {m.user.first_name ? `${m.user.first_name} ${m.user.last_name}` : m.user.username}
                    {m.role === 'owner' && (
                      <Crown className="w-3.5 h-3.5 text-amber-400" />
                    )}
                  </div>
                  <div className="text-xs text-slate-400">
                    {m.user.email || m.user.username} • <span className="capitalize text-indigo-300 font-medium">{m.role}</span>
                  </div>
                </div>

                {isOwnerOrAdmin && m.role !== 'owner' && (
                  <button
                    onClick={() => handleRemoveMember(m.id)}
                    className="p-1.5 rounded-lg text-slate-500 hover:text-rose-400 hover:bg-rose-500/10 transition cursor-pointer"
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
        <div className="p-6 rounded-2xl bg-slate-900 border border-slate-800 space-y-4">
          <div className="flex items-center justify-between">
            <h2 className="text-base font-bold text-white flex items-center gap-2">
              <UserPlus className="w-5 h-5 text-indigo-400" />
              Invite Team Member
            </h2>
          </div>

          {isOwnerOrAdmin ? (
            <form onSubmit={handleCreateInvite} className="space-y-3">
              <div>
                <label className="block text-xs font-medium text-slate-300 mb-1">
                  Recipient Email
                </label>
                <input
                  type="email"
                  value={inviteEmail}
                  onChange={(e) => setInviteEmail(e.target.value)}
                  placeholder="colleague@enterprise.com"
                  className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-indigo-500"
                  required
                />
              </div>

              <div>
                <label className="block text-xs font-medium text-slate-300 mb-1">
                  Role Assignment
                </label>
                <select
                  value={inviteRole}
                  onChange={(e) => setInviteRole(e.target.value)}
                  className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-indigo-500"
                >
                  <option value="member">Member (Read & Query Knowledge)</option>
                  <option value="editor">Editor (Upload & Manage Documents)</option>
                  <option value="admin">Administrator (Manage Settings & Policies)</option>
                </select>
              </div>

              <button
                type="submit"
                className="w-full py-2.5 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white font-semibold text-xs shadow-md shadow-indigo-600/30 transition flex items-center justify-center gap-2 cursor-pointer"
              >
                <UserPlus className="w-4 h-4" />
                Generate Enterprise Invitation
              </button>
            </form>
          ) : (
            <p className="text-xs text-slate-400">
              Only organization owners and administrators can invite new members.
            </p>
          )}

          {/* Pending Invitations list */}
          {invitations.length > 0 && (
            <div className="pt-2 border-t border-slate-800">
              <h3 className="text-xs font-semibold uppercase tracking-wider text-slate-400 mb-2">
                Pending Invitations ({invitations.length})
              </h3>
              <div className="space-y-2 max-h-40 overflow-y-auto">
                {invitations.map((inv) => (
                  <div key={inv.id} className="p-2.5 rounded-lg bg-slate-950/60 border border-slate-800 flex items-center justify-between text-xs">
                    <div>
                      <div className="font-medium text-white">{inv.email}</div>
                      <div className="text-[11px] text-slate-400">
                        Role: <span className="text-indigo-400 capitalize">{inv.role}</span> • {inv.is_accepted ? 'Accepted' : 'Pending'}
                      </div>
                    </div>
                    <button
                      onClick={() => copyToClipboard(inv.token)}
                      className="flex items-center gap-1 px-2 py-1 rounded bg-slate-800 hover:bg-slate-700 text-slate-300 text-[11px] transition cursor-pointer"
                    >
                      {copiedToken === inv.token ? <Check className="w-3 h-3 text-emerald-400" /> : <Copy className="w-3 h-3" />}
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
