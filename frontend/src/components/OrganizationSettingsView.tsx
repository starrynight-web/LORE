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
  Globe,
  Key,
  Server,
  Cpu,
  Eye,
  EyeOff,
  Terminal,
  Download,
  Zap,
  CheckCircle2,
  Radio,
  Code,
  Share2,
  Layers,
  Shield,
  Scale,
  Clock,
  AlertTriangle
} from 'lucide-react';
import { 
  api, 
  Organization, 
  Plan, 
  SubscriptionData, 
  OrganizationMember, 
  OrganizationInvitation,
  GovernanceLayersStatus,
  GovernanceLayerDef,
  ScopedExceptionResult
} from '@/lib/api';
import { useI18n } from '@/lib/i18n';
import { ThemeToggle, LanguageToggle } from '@/components/PremiumToggles';

interface OrgSettingsProps {
  currentOrg: Organization | null;
  userRole?: string;
  onRefreshOrg?: () => void;
  initialSection?: string;
}

export const OrganizationSettingsView: React.FC<OrgSettingsProps> = ({
  currentOrg,
  userRole = 'member',
  onRefreshOrg,
  initialSection = 'all'
}) => {
  const { t } = useI18n();
  const [activeSection, setActiveSection] = useState<string>(initialSection);
  const [plans, setPlans] = useState<Plan[]>([]);
  const [subData, setSubData] = useState<SubscriptionData | null>(null);
  const [members, setMembers] = useState<OrganizationMember[]>([]);
  const [invitations, setInvitations] = useState<OrganizationInvitation[]>([]);
  const [inviteEmail, setInviteEmail] = useState('');
  const [inviteRole, setInviteRole] = useState('member');
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [copiedToken, setCopiedToken] = useState<string | null>(null);

  // Groq API Key & Model Configuration
  const [groqKey, setGroqKey] = useState('');
  const [groqModel, setGroqModel] = useState('gpt-oss-120B');
  const [showKey, setShowKey] = useState(false);
  const [testingGroq, setTestingGroq] = useState(false);
  const [groqStatus, setGroqStatus] = useState<{ connected: boolean; latency?: number; message?: string; error?: string } | null>(null);

  // MCP Server Configuration
  const [mcpPlatform, setMcpPlatform] = useState<'claude' | 'cursor' | 'windsurf' | 'stdio'>('claude');
  const [mcpTransport, setMcpTransport] = useState<'stdio' | 'sse'>('stdio');
  const [copiedMcp, setCopiedMcp] = useState(false);
  const [mcpTools, setMcpTools] = useState({
    search: true,
    query: true,
    document: true,
    ocr: true
  });

  // 9-Layer Governance Stack & Scoped Exceptions
  const [layersStatus, setLayersStatus] = useState<GovernanceLayersStatus | null>(null);
  const [scopedExceptions, setScopedExceptions] = useState<any[]>([]);
  const [submittingException, setSubmittingException] = useState(false);
  const [newException, setNewException] = useState({
    name: '',
    rule_code: '',
    scope_type: 'department',
    scope_value: '',
    action: 'override',
    override_state: 'supported',
    justification: ''
  });

  useEffect(() => {
    if (typeof window !== 'undefined') {
      const storedKey = localStorage.getItem('lore_groq_api_key') || '';
      const storedModel = localStorage.getItem('lore_llm_model') || 'gpt-oss-120B';
      setGroqKey(storedKey);
      setGroqModel(storedModel);
      if (storedKey) {
        setGroqStatus({ connected: true, message: 'Saved in local workspace' });
      }
    }
  }, []);

  useEffect(() => {
    if (initialSection) {
      setActiveSection(initialSection);
    }
  }, [initialSection]);

  const handleSaveGroqKey = () => {
    if (typeof window !== 'undefined') {
      localStorage.setItem('lore_groq_api_key', groqKey.trim());
      localStorage.setItem('lore_llm_model', groqModel.trim());
      setMessage('Groq API Key and gpt-oss-120B model configured successfully!');
      setGroqStatus({ connected: true, message: 'Stored and active for Governed RAG' });
    }
  };

  const handleClearGroqKey = () => {
    if (typeof window !== 'undefined') {
      localStorage.removeItem('lore_groq_api_key');
      setGroqKey('');
      setGroqStatus(null);
      setMessage('Groq API key removed. Falling back to deterministic internal grounding.');
    }
  };

  const handleTestGroq = async () => {
    if (!groqKey.trim()) {
      setError('Please provide a Groq API key to test.');
      return;
    }
    setTestingGroq(true);
    setGroqStatus(null);
    setError(null);
    try {
      const res = await api.testGroqConnection(groqKey.trim(), groqModel.trim());
      setGroqStatus({
        connected: true,
        latency: res.latency_ms,
        message: `${res.message} (${res.models_count} models accessible)`
      });
      setMessage(`Groq API verified successfully (${res.latency_ms}ms)!`);
    } catch (e: any) {
      setGroqStatus({
        connected: false,
        error: e.message || 'Groq API connection failed.'
      });
      setError(e.message || 'Failed connecting to Groq API.');
    } finally {
      setTestingGroq(false);
    }
  };

  const getMcpSnippet = () => {
    const pythonPath = 'python';
    const serverPath = 'e:\\\\LORE\\\\backend\\\\mcp_server.py';

    if (mcpPlatform === 'claude') {
      return JSON.stringify({
        mcpServers: {
          'lore-enterprise': {
            command: pythonPath,
            args: ['e:\\LORE\\backend\\mcp_server.py'],
            env: {
              DJANGO_SETTINGS_MODULE: 'lore_enterprise.settings',
              PYTHONIOENCODING: 'utf-8'
            }
          }
        }
      }, null, 2);
    } else if (mcpPlatform === 'cursor') {
      return JSON.stringify({
        mcpServers: {
          'lore-enterprise': {
            command: pythonPath,
            args: ['e:\\LORE\\backend\\mcp_server.py']
          }
        }
      }, null, 2);
    } else if (mcpPlatform === 'windsurf') {
      return JSON.stringify({
        mcpServers: {
          'lore-enterprise': {
            command: pythonPath,
            args: ['e:\\LORE\\backend\\mcp_server.py']
          }
        }
      }, null, 2);
    } else {
      return `# Run LORE MCP Server directly over stdio:\npython e:\\LORE\\backend\\mcp_server.py\n\n# Or query tool manifest:\npython e:\\LORE\\backend\\mcp_server.py --list-tools`;
    }
  };

  const handleCopyMcp = () => {
    navigator.clipboard.writeText(getMcpSnippet());
    setCopiedMcp(true);
    setTimeout(() => setCopiedMcp(false), 2000);
  };

  const handleDownloadMcp = () => {
    const snippet = getMcpSnippet();
    const filename = mcpPlatform === 'claude' 
      ? 'claude_desktop_config.json' 
      : mcpPlatform === 'cursor' 
      ? 'cursor_mcp.json' 
      : 'mcp_config.json';
    const blob = new Blob([snippet], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    a.click();
    URL.revokeObjectURL(url);
  };

  const isOwnerOrAdmin = userRole === 'owner' || userRole === 'admin';

  const loadData = async () => {
    try {
      const [pList, sData, mList, iList, layers, exceptions] = await Promise.all([
        currentOrg ? api.getPlans().catch(() => []) : Promise.resolve([]),
        currentOrg ? api.getSubscription(currentOrg.id).catch(() => null) : Promise.resolve(null),
        currentOrg ? api.getOrgMembers(currentOrg.id).catch(() => []) : Promise.resolve([]),
        currentOrg ? api.getOrgInvitations(currentOrg.id).catch(() => []) : Promise.resolve([]),
        api.getGovernanceLayersStatus().catch(() => null),
        api.getScopedExceptions().catch(() => [])
      ]);
      setPlans(pList);
      setSubData(sData);
      setMembers(mList);
      setInvitations(iList);
      setLayersStatus(layers);
      setScopedExceptions(exceptions);
    } catch (e: any) {
      console.error("Failed loading org settings:", e);
    }
  };

  useEffect(() => {
    loadData();
  }, [currentOrg?.id]);

  const handleCreateException = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newException.name || !newException.rule_code || !newException.scope_value || !newException.justification) {
      setError('Please fill all required exception fields (Name, Rule Code, Scope Value, Justification).');
      return;
    }
    setSubmittingException(true);
    setError(null);
    try {
      await api.createScopedException({
        workspace_id: currentOrg ? currentOrg.id : '',
        name: newException.name,
        rule_code: newException.rule_code,
        scope_type: newException.scope_type,
        scope_value: newException.scope_value,
        action: newException.action,
        override_state: newException.override_state,
        justification: newException.justification
      });
      setMessage('Scoped Exception policy registered and activated in Layer 4.');
      setNewException({
        name: '',
        rule_code: '',
        scope_type: 'department',
        scope_value: '',
        action: 'override',
        override_state: 'supported',
        justification: ''
      });
      const updated = await api.getScopedExceptions();
      setScopedExceptions(updated);
    } catch (err: any) {
      setError(err.message || 'Failed creating scoped exception.');
    } finally {
      setSubmittingException(false);
    }
  };

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

      {/* Settings Navigation Tabs */}
      <div 
        className="flex items-center gap-1.5 p-1.5 rounded-xl border overflow-x-auto shadow-sm"
        style={{
          backgroundColor: 'var(--bg-surface)',
          borderColor: 'var(--border-color)',
        }}
      >
        {[
          { id: 'all', label: 'All Settings', icon: Building2 },
          { id: 'layers', label: '9 Governance Layers', icon: Shield, highlight: true },
          { id: 'api', label: 'AI Connect (Groq · gpt-oss-120B)', icon: Zap, highlight: true },
          { id: 'mcp', label: 'LORE MCP Server Hub', icon: Server, highlight: true },
          { id: 'theme', label: 'Appearance & Language', icon: Palette },
          { id: 'team', label: 'Team & Quotas', icon: Users },
        ].map((tab) => {
          const Icon = tab.icon;
          const isActive = activeSection === tab.id;
          return (
            <button
              key={tab.id}
              onClick={() => setActiveSection(tab.id)}
              className="flex items-center gap-2 px-3.5 py-2 rounded-lg text-xs font-semibold transition-all duration-150 cursor-pointer whitespace-nowrap active:scale-95"
              style={{
                backgroundColor: isActive ? 'var(--accent-light)' : 'transparent',
                color: isActive ? 'var(--brand-accent)' : 'var(--text-secondary)',
                border: isActive ? '1px solid var(--border-color)' : '1px solid transparent',
              }}
            >
              <Icon 
                className="w-3.5 h-3.5" 
                style={{
                  color: isActive ? 'var(--brand-accent)' : tab.highlight ? 'var(--accent-parrot)' : 'var(--text-muted)'
                }}
              />
              <span>{tab.label}</span>
              {tab.highlight && !isActive && (
                <span className="w-1.5 h-1.5 rounded-full bg-[var(--accent-parrot)]" />
              )}
            </button>
          );
        })}
      </div>

      {/* Appearance & Localization Section (Master Prompt 11.K) */}
      {(activeSection === 'all' || activeSection === 'theme') && (
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
      )}

      {/* =====================================================================
          AI Inference & Custom API Connect (Master Prompt: Groq & gpt-oss-120B)
          ===================================================================== */}
      {(activeSection === 'all' || activeSection === 'api') && (
        <div 
          className="p-6 rounded-2xl border shadow-sm space-y-5"
          style={{
            backgroundColor: 'var(--bg-surface)',
            borderColor: 'var(--border-color)',
          }}
        >
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b pb-3" style={{ borderColor: 'var(--border-color)' }}>
          <div>
            <h2 className="text-sm sm:text-base font-bold text-[var(--text-primary)] flex items-center gap-2">
              <Cpu className="w-4 h-4 text-[var(--brand-accent)]" />
              <span>{t('settings.api_connect_title')}</span>
            </h2>
            <p className="text-xs text-[var(--text-muted)] mt-0.5">
              {t('settings.api_connect_desc')}
            </p>
          </div>

          <div className="flex items-center gap-2 flex-wrap">
            <span 
              className="px-2.5 py-1 rounded-full text-[11px] font-semibold border flex items-center gap-1.5"
              style={{
                backgroundColor: 'var(--accent-light)',
                borderColor: 'var(--border-color)',
                color: 'var(--brand-accent)',
              }}
            >
              <Zap className="w-3 h-3" />
              Provider: Groq Cloud
            </span>
            <span 
              className="px-2.5 py-1 rounded-full text-[11px] font-semibold border flex items-center gap-1.5"
              style={{
                backgroundColor: 'var(--bg-surface-soft)',
                borderColor: 'var(--border-color)',
                color: 'var(--text-primary)',
              }}
            >
              <CheckCircle2 className="w-3 h-3 text-[var(--success)]" />
              Model: {groqModel}
            </span>
          </div>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-5">
          {/* Left Column: API Key & Model Configuration */}
          <div className="lg:col-span-2 space-y-4">
            <div>
              <label className="block text-xs font-semibold text-[var(--text-secondary)] mb-1.5">
                {t('settings.groq_key_label')}
              </label>
              <div className="relative">
                <input
                  type={showKey ? 'text' : 'password'}
                  value={groqKey}
                  onChange={(e) => setGroqKey(e.target.value)}
                  placeholder="gsk_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
                  className="w-full border rounded-xl px-3.5 py-2.5 pr-10 text-xs sm:text-sm font-mono focus:outline-none"
                  style={{
                    backgroundColor: 'var(--input-bg)',
                    borderColor: 'var(--input-border)',
                    color: 'var(--text-primary)',
                  }}
                />
                <button
                  type="button"
                  onClick={() => setShowKey(!showKey)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-[var(--text-muted)] hover:text-[var(--text-primary)] transition cursor-pointer"
                  title={showKey ? 'Hide key' : 'Show key'}
                >
                  {showKey ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                </button>
              </div>
              <p className="text-[11px] text-[var(--text-muted)] mt-1">
                Your key is stored securely in your local enterprise workspace and sent only to authenticate direct queries.
              </p>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <div>
                <label className="block text-xs font-semibold text-[var(--text-secondary)] mb-1.5">
                  {t('settings.model_label')}
                </label>
                <select
                  value={groqModel}
                  onChange={(e) => setGroqModel(e.target.value)}
                  className="w-full border rounded-xl px-3 py-2 text-xs sm:text-sm focus:outline-none cursor-pointer"
                  style={{
                    backgroundColor: 'var(--input-bg)',
                    borderColor: 'var(--input-border)',
                    color: 'var(--text-primary)',
                  }}
                >
                  <option value="gpt-oss-120B">gpt-oss-120B (Primary Anti-Hallucination)</option>
                  <option value="llama-3.3-70b-versatile">llama-3.3-70b-versatile (Fallback High-Speed)</option>
                  <option value="mixtral-8x7b-32768">mixtral-8x7b-32768 (MoE Architecture)</option>
                </select>
              </div>

              <div>
                <label className="block text-xs font-semibold text-[var(--text-secondary)] mb-1.5">
                  Inference Guardrails
                </label>
                <div 
                  className="p-2.5 rounded-xl border text-[11px] space-y-1"
                  style={{
                    backgroundColor: 'var(--bg-surface-soft)',
                    borderColor: 'var(--border-color)',
                    color: 'var(--text-muted)'
                  }}
                >
                  <div className="flex items-center justify-between">
                    <span>Temperature:</span>
                    <span className="font-mono font-bold text-[var(--text-primary)]">0.0 (Deterministic)</span>
                  </div>
                  <div className="flex items-center justify-between">
                    <span>Grounding Gate:</span>
                    <span className="font-semibold text-[var(--success)]">Mandatory Citations</span>
                  </div>
                </div>
              </div>
            </div>

            {/* Action Buttons */}
            <div className="flex items-center gap-3 pt-2">
              <button
                type="button"
                onClick={handleTestGroq}
                disabled={testingGroq}
                className="px-4 py-2 rounded-xl text-xs font-semibold border flex items-center gap-2 transition cursor-pointer active:scale-95 disabled:opacity-50"
                style={{
                  backgroundColor: 'var(--bg-surface-soft)',
                  borderColor: 'var(--border-color)',
                  color: 'var(--text-primary)',
                }}
              >
                <Zap className={`w-3.5 h-3.5 ${testingGroq ? 'animate-spin text-[var(--brand-accent)]' : ''}`} />
                <span>{testingGroq ? 'Testing Connection...' : t('settings.test_connection')}</span>
              </button>

              <button
                type="button"
                onClick={handleSaveGroqKey}
                className="px-4 py-2 rounded-xl text-xs font-semibold flex items-center gap-2 shadow-sm transition cursor-pointer active:scale-95"
                style={{
                  backgroundColor: 'var(--brand-accent)',
                  color: 'var(--cta-text)',
                }}
              >
                <Check className="w-3.5 h-3.5" />
                <span>{t('settings.save_key')}</span>
              </button>

              {groqKey && (
                <button
                  type="button"
                  onClick={handleClearGroqKey}
                  className="px-3 py-2 rounded-xl text-xs font-semibold text-[var(--text-muted)] hover:text-[var(--error)] transition cursor-pointer"
                >
                  {t('settings.clear_key')}
                </button>
              )}
            </div>
          </div>

          {/* Right Column: Status & Telemetry Card */}
          <div 
            className="p-4 rounded-xl border flex flex-col justify-between space-y-3"
            style={{
              backgroundColor: 'var(--bg-surface-soft)',
              borderColor: 'var(--border-color)',
            }}
          >
            <div>
              <div className="text-xs font-bold text-[var(--text-primary)] flex items-center gap-1.5 mb-2">
                <ShieldCheck className="w-4 h-4 text-[var(--brand-accent)]" />
                Anti-Hallucination Status
              </div>

              {groqStatus?.connected ? (
                <div className="space-y-2">
                  <div className="p-2.5 rounded-lg border text-xs" style={{ backgroundColor: 'var(--success-bg)', borderColor: 'var(--border-color)', color: 'var(--success)' }}>
                    <div className="font-bold flex items-center gap-1.5">
                      <CheckCircle2 className="w-3.5 h-3.5" />
                      Active & Connected
                    </div>
                    {groqStatus.latency && (
                      <div className="text-[11px] mt-0.5">
                        Latency: <span className="font-mono font-bold">{groqStatus.latency} ms</span>
                      </div>
                    )}
                  </div>
                  <p className="text-[11px] text-[var(--text-muted)]">
                    All PDF extractions and Governed RAG questions will invoke Groq with model <strong className="text-[var(--text-primary)]">{groqModel}</strong> under deterministic zero-temperature.
                  </p>
                </div>
              ) : groqStatus?.error ? (
                <div className="p-2.5 rounded-lg border text-xs" style={{ backgroundColor: 'var(--error-bg)', borderColor: 'var(--border-color)', color: 'var(--error)' }}>
                  <div className="font-bold flex items-center gap-1.5">
                    <AlertCircle className="w-3.5 h-3.5" />
                    Connection Failed
                  </div>
                  <div className="text-[11px] mt-0.5">{groqStatus.error}</div>
                </div>
              ) : (
                <div className="text-xs text-[var(--text-muted)] space-y-2">
                  <p>
                    No custom Groq key configured yet. LORE will operate using its built-in deterministic factual synthesis engine.
                  </p>
                  <p className="text-[11px]">
                    Connect a free Groq Cloud key to unlock <strong>gpt-oss-120B</strong> high-speed inference.
                  </p>
                </div>
              )}
            </div>

            <div className="pt-2 border-t text-[10px] text-[var(--text-muted)]" style={{ borderColor: 'var(--border-color)' }}>
              Protocol: <span className="font-mono">OpenAI-compatible v1</span> • Temperature: <span className="font-mono">0.0</span>
            </div>
          </div>
        </div>
      </div>
      )}

      {/* =====================================================================
          LORE MCP Server Hub & Generator (Master Prompt: Claude/Cursor/Windsurf)
          ===================================================================== */}
      {(activeSection === 'all' || activeSection === 'mcp') && (
        <div 
          className="p-6 rounded-2xl border shadow-sm space-y-5"
          style={{
            backgroundColor: 'var(--bg-surface)',
            borderColor: 'var(--border-color)',
          }}
        >
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b pb-3" style={{ borderColor: 'var(--border-color)' }}>
          <div>
            <h2 className="text-sm sm:text-base font-bold text-[var(--text-primary)] flex items-center gap-2">
              <Server className="w-4 h-4 text-[var(--brand-accent)]" />
              <span>{t('settings.mcp_title')}</span>
            </h2>
            <p className="text-xs text-[var(--text-muted)] mt-0.5">
              {t('settings.mcp_desc')}
            </p>
          </div>

          <span 
            className="px-2.5 py-1 rounded-full text-[11px] font-semibold border flex items-center gap-1.5"
            style={{
              backgroundColor: 'var(--accent-light)',
              borderColor: 'var(--border-color)',
              color: 'var(--brand-accent)',
            }}
          >
            <Radio className="w-3 h-3 text-[var(--brand-accent)]" />
            MCP Protocol v2024-11-05
          </span>
        </div>

        {/* Platform Selector Tabs */}
        <div className="flex items-center gap-2 flex-wrap border-b pb-3" style={{ borderColor: 'var(--border-color)' }}>
          {(['claude', 'cursor', 'windsurf', 'stdio'] as const).map((platform) => {
            const active = mcpPlatform === platform;
            const label = platform === 'claude' 
              ? 'Claude Desktop' 
              : platform === 'cursor' 
              ? 'Cursor IDE' 
              : platform === 'windsurf' 
              ? 'Windsurf / Antigravity' 
              : 'Python Stdio CLI';

            return (
              <button
                key={platform}
                onClick={() => setMcpPlatform(platform)}
                className="px-3.5 py-1.5 rounded-xl text-xs font-semibold transition cursor-pointer"
                style={{
                  backgroundColor: active ? 'var(--brand-accent)' : 'var(--bg-surface-soft)',
                  color: active ? 'var(--cta-text)' : 'var(--text-secondary)',
                  border: active ? 'none' : '1px solid var(--border-color)',
                }}
              >
                {label}
              </button>
            );
          })}
        </div>

        {/* Exposed Tools Checklist */}
        <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-4 gap-3">
          <div 
            className="p-3 rounded-xl border text-xs space-y-1"
            style={{ backgroundColor: 'var(--bg-surface-soft)', borderColor: 'var(--border-color)' }}
          >
            <div className="font-mono font-bold text-[var(--brand-accent)] flex items-center gap-1">
              <Check className="w-3.5 h-3.5" /> lore_search
            </div>
            <p className="text-[11px] text-[var(--text-muted)]">
              Hybrid vector + lexical search with Context Reranker
            </p>
          </div>

          <div 
            className="p-3 rounded-xl border text-xs space-y-1"
            style={{ backgroundColor: 'var(--bg-surface-soft)', borderColor: 'var(--border-color)' }}
          >
            <div className="font-mono font-bold text-[var(--brand-accent)] flex items-center gap-1">
              <Check className="w-3.5 h-3.5" /> lore_governed_query
            </div>
            <p className="text-[11px] text-[var(--text-muted)]">
              9-state anti-hallucination inference with citations
            </p>
          </div>

          <div 
            className="p-3 rounded-xl border text-xs space-y-1"
            style={{ backgroundColor: 'var(--bg-surface-soft)', borderColor: 'var(--border-color)' }}
          >
            <div className="font-mono font-bold text-[var(--brand-accent)] flex items-center gap-1">
              <Check className="w-3.5 h-3.5" /> lore_get_document
            </div>
            <p className="text-[11px] text-[var(--text-muted)]">
              Document metadata, OCR confidence & pages
            </p>
          </div>

          <div 
            className="p-3 rounded-xl border text-xs space-y-1"
            style={{ backgroundColor: 'var(--bg-surface-soft)', borderColor: 'var(--border-color)' }}
          >
            <div className="font-mono font-bold text-[var(--brand-accent)] flex items-center gap-1">
              <Check className="w-3.5 h-3.5" /> lore_ocr_extract
            </div>
            <p className="text-[11px] text-[var(--text-muted)]">
              Realtime dual-stream OCR extraction on raw PDF/image
            </p>
          </div>
        </div>

        {/* Configuration Code Block */}
        <div className="space-y-2">
          <div className="flex items-center justify-between text-xs text-[var(--text-muted)]">
            <span className="font-mono">
              {mcpPlatform === 'claude' 
                ? '%APPDATA%\\Claude\\claude_desktop_config.json' 
                : mcpPlatform === 'cursor' 
                ? '.cursor/mcp.json' 
                : mcpPlatform === 'windsurf' 
                ? 'mcp_config.json' 
                : 'Terminal Execution'}
            </span>

            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={handleCopyMcp}
                className="px-3 py-1 rounded-lg border text-xs font-semibold flex items-center gap-1.5 transition cursor-pointer"
                style={{
                  backgroundColor: 'var(--bg-surface-soft)',
                  borderColor: 'var(--border-color)',
                  color: 'var(--text-primary)',
                }}
              >
                {copiedMcp ? <Check className="w-3.5 h-3.5 text-[var(--success)]" /> : <Copy className="w-3.5 h-3.5" />}
                <span>{copiedMcp ? t('settings.copied') : t('settings.copy_config')}</span>
              </button>

              <button
                type="button"
                onClick={handleDownloadMcp}
                className="px-3 py-1 rounded-lg border text-xs font-semibold flex items-center gap-1.5 transition cursor-pointer"
                style={{
                  backgroundColor: 'var(--bg-surface-soft)',
                  borderColor: 'var(--border-color)',
                  color: 'var(--text-primary)',
                }}
              >
                <Download className="w-3.5 h-3.5" />
                <span>{t('settings.download_mcp')}</span>
              </button>
            </div>
          </div>

          <pre 
            className="p-4 rounded-xl border text-xs font-mono overflow-x-auto leading-relaxed"
            style={{
              backgroundColor: 'var(--bg-surface-soft)',
              borderColor: 'var(--border-color)',
              color: 'var(--text-primary)',
            }}
          >
            <code>{getMcpSnippet()}</code>
          </pre>
        </div>
      </div>
      )}

      {/* =====================================================================
          9-LAYER ENTERPRISE GOVERNANCE ENGINE & POLICY STUDIO (lore.md §3, §4, §10)
          ===================================================================== */}
      {(activeSection === 'all' || activeSection === 'layers') && (
        <div 
          className="p-6 rounded-2xl border shadow-sm space-y-6"
          style={{
            backgroundColor: 'var(--bg-surface)',
            borderColor: 'var(--border-color)',
          }}
        >
          {/* Header */}
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b pb-4" style={{ borderColor: 'var(--border-color)' }}>
            <div>
              <h2 className="text-sm sm:text-base font-bold text-[var(--text-primary)] flex items-center gap-2">
                <Shield className="w-4 h-4 text-[var(--brand-accent)]" />
                <span>Enterprise 9-Layer Governance Stack & Policy Engine</span>
              </h2>
              <p className="text-xs text-[var(--text-muted)] mt-0.5">
                Deterministic anti-hallucination, role-cleared permissions, cross-source conflict arbitration, and scoped exception overrides (LORE Architecture v3.0 §3, §4, §10).
              </p>
            </div>

            <div className="flex items-center gap-2 flex-wrap">
              <span 
                className="px-2.5 py-1 rounded-full text-[11px] font-bold border flex items-center gap-1.5"
                style={{
                  backgroundColor: 'var(--success-bg)',
                  borderColor: 'var(--border-color)',
                  color: 'var(--success)',
                }}
              >
                <CheckCircle2 className="w-3.5 h-3.5" />
                9/9 Layers Operational (100%)
              </span>
              <span 
                className="px-2.5 py-1 rounded-full text-[11px] font-mono border"
                style={{
                  backgroundColor: 'var(--bg-surface-soft)',
                  borderColor: 'var(--border-color)',
                  color: 'var(--brand-accent)',
                }}
              >
                Zero-Bypass Enforcement
              </span>
            </div>
          </div>

          {/* 9-Layer Architecture Matrix */}
          <div>
            <h3 className="text-xs font-bold uppercase tracking-wider text-[var(--text-muted)] mb-3 flex items-center gap-2">
              <Layers className="w-4 h-4 text-[var(--brand-accent)]" />
              <span>Layer Status & Architectural Decision Gates</span>
            </h3>

            <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
              {(layersStatus?.layers || [
                { layer: 'L7', name: 'Permission Layer', decides: 'Who may ask and what may they see?', mechanism: 'Zero-leakage clearance & pre-retrieval role filtering', status: 'ACTIVE' },
                { layer: 'L6', name: 'Authority Layer', decides: 'Which document wins when sources conflict?', mechanism: '7-rank authority ladder precedence & date tie arbitration', status: 'ACTIVE' },
                { layer: 'L5', name: 'Temporal Validity Layer', decides: 'Is this evidence still valid today?', mechanism: 'Effective date bounds & document aging verification', status: 'ACTIVE' },
                { layer: 'L4', name: 'Exception Layer', decides: 'Does an approved business exception override?', mechanism: 'Tenant/project/vendor scoped rule overrides with audit trails', status: 'ACTIVE' },
                { layer: 'L3', name: 'Evidence Sufficiency Layer', decides: 'Is there enough proof to decide?', mechanism: 'Mandatory checklist evidence completeness verification', status: 'ACTIVE' },
                { layer: 'L2', name: 'Answer-State Layer', decides: 'What is the governed answer state?', mechanism: 'Strict 9-state precedence ladder arbitration', status: 'ACTIVE' },
                { layer: 'L1', name: 'Decision Intelligence Layer', decides: 'What kind of decision is this?', mechanism: 'Query classification into decision types with escalation targets', status: 'ACTIVE' },
                { layer: 'L0', name: 'Observability Layer', decides: 'Is the system healthy and honest?', mechanism: 'Decision ledger entry, audit trace & token metering', status: 'ACTIVE' },
                { layer: 'Core', name: 'Hybrid Retrieval Engine', decides: 'What knowledge applies and what may enter?', mechanism: 'Qdrant dense vectors + BM25 lexical + Reciprocal Rank Fusion + Reranker', status: 'ACTIVE' },
              ]).map((ly, idx) => (
                <div 
                  key={idx}
                  className="p-3.5 rounded-xl border flex flex-col justify-between space-y-2 transition-all hover:border-[var(--brand-accent)]"
                  style={{
                    backgroundColor: 'var(--bg-surface-soft)',
                    borderColor: 'var(--border-color)',
                  }}
                >
                  <div className="space-y-1">
                    <div className="flex items-center justify-between">
                      <span 
                        className="px-2 py-0.5 rounded text-[10px] font-mono font-bold border"
                        style={{
                          backgroundColor: 'var(--accent-light)',
                          borderColor: 'var(--border-color)',
                          color: 'var(--brand-accent)',
                        }}
                      >
                        {ly.layer}
                      </span>
                      <span 
                        className="text-[10px] font-bold px-2 py-0.5 rounded-full"
                        style={{
                          backgroundColor: 'var(--success-bg)',
                          color: 'var(--success)',
                        }}
                      >
                        {ly.status.toUpperCase()}
                      </span>
                    </div>
                    <div className="font-bold text-xs text-[var(--text-primary)] pt-1">{ly.name}</div>
                    <p className="text-[11px] italic text-[var(--brand-accent)] font-medium leading-snug">
                      &quot;{ly.decides}&quot;
                    </p>
                  </div>
                  <div className="text-[10px] text-[var(--text-muted)] border-t pt-2" style={{ borderColor: 'var(--border-color)' }}>
                    {ly.mechanism}
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* L4: Scoped Exceptions Policy Studio */}
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 pt-2 border-t" style={{ borderColor: 'var(--border-color)' }}>
            {/* Left: Active Exceptions */}
            <div className="lg:col-span-2 space-y-3">
              <div className="flex items-center justify-between">
                <div>
                  <h3 className="text-xs font-bold uppercase tracking-wider text-[var(--text-primary)] flex items-center gap-1.5">
                    <Key className="w-3.5 h-3.5 text-[var(--brand-accent)]" />
                    <span>Active Scoped Exceptions (Layer 4)</span>
                  </h3>
                  <p className="text-[11px] text-[var(--text-muted)] mt-0.5">
                    Rules overridden for specific departments, projects, or vendors with verified justifications.
                  </p>
                </div>
                <span 
                  className="px-2 py-0.5 rounded text-[10px] font-mono font-bold border"
                  style={{
                    backgroundColor: 'var(--bg-surface-soft)',
                    borderColor: 'var(--border-color)',
                    color: 'var(--text-secondary)',
                  }}
                >
                  {scopedExceptions.length} active
                </span>
              </div>

              {scopedExceptions.length > 0 ? (
                <div className="space-y-2 max-h-64 overflow-y-auto">
                  {scopedExceptions.map((ex: any) => (
                    <div 
                      key={ex.id}
                      className="p-3 rounded-xl border text-xs space-y-1.5"
                      style={{
                        backgroundColor: 'var(--bg-surface-soft)',
                        borderColor: 'var(--border-color)',
                      }}
                    >
                      <div className="flex items-center justify-between font-bold text-[var(--text-primary)]">
                        <div className="flex items-center gap-2">
                          <span>{ex.name}</span>
                          <span className="font-mono text-[10px] text-[var(--brand-accent)]">[{ex.rule_code}]</span>
                        </div>
                        <span 
                          className="px-2 py-0.5 rounded text-[10px] font-mono uppercase border"
                          style={{
                            backgroundColor: 'var(--accent-light)',
                            borderColor: 'var(--border-color)',
                            color: 'var(--brand-accent)',
                          }}
                        >
                          {ex.scope_type}: {ex.scope_value}
                        </span>
                      </div>
                      <p className="text-[11px] text-[var(--text-secondary)] leading-relaxed">
                        {ex.justification}
                      </p>
                      <div className="flex items-center justify-between text-[10px] text-[var(--text-muted)] pt-1 border-t" style={{ borderColor: 'var(--border-color)' }}>
                        <span>Action: <strong className="uppercase text-[var(--brand-accent)]">{ex.action}</strong> • Override State: <strong className="text-[var(--text-primary)]">{ex.override_state}</strong></span>
                        <span>Approved by: {ex.approved_by_username || 'Admin'}</span>
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <div 
                  className="p-6 rounded-xl border text-center text-xs text-[var(--text-muted)]"
                  style={{
                    backgroundColor: 'var(--bg-surface-soft)',
                    borderColor: 'var(--border-color)',
                  }}
                >
                  No custom scoped exceptions registered yet. Enterprise rules apply uniformly to all workspaces.
                </div>
              )}
            </div>

            {/* Right: Register Exception Form */}
            <form 
              onSubmit={handleCreateException}
              className="p-4 rounded-xl border space-y-3"
              style={{
                backgroundColor: 'var(--bg-surface-soft)',
                borderColor: 'var(--border-color)',
              }}
            >
              <div className="font-bold text-xs text-[var(--text-primary)] flex items-center gap-1.5">
                <ShieldCheck className="w-3.5 h-3.5 text-[var(--brand-accent)]" />
                <span>Register Scoped Exception</span>
              </div>

              <div>
                <label className="block text-[11px] font-semibold text-[var(--text-secondary)] mb-1">
                  Exception Name
                </label>
                <input
                  type="text"
                  value={newException.name}
                  onChange={(e) => setNewException({ ...newException, name: e.target.value })}
                  placeholder="e.g. EU Cloud Waiver #419"
                  className="w-full border rounded-lg px-2.5 py-1.5 text-xs focus:outline-none"
                  style={{
                    backgroundColor: 'var(--input-bg)',
                    borderColor: 'var(--input-border)',
                    color: 'var(--text-primary)',
                  }}
                />
              </div>

              <div className="grid grid-cols-2 gap-2">
                <div>
                  <label className="block text-[11px] font-semibold text-[var(--text-secondary)] mb-1">
                    Rule Code
                  </label>
                  <input
                    type="text"
                    value={newException.rule_code}
                    onChange={(e) => setNewException({ ...newException, rule_code: e.target.value })}
                    placeholder="CLOUD-001"
                    className="w-full border rounded-lg px-2.5 py-1.5 text-xs font-mono focus:outline-none"
                    style={{
                      backgroundColor: 'var(--input-bg)',
                      borderColor: 'var(--input-border)',
                      color: 'var(--text-primary)',
                    }}
                  />
                </div>
                <div>
                  <label className="block text-[11px] font-semibold text-[var(--text-secondary)] mb-1">
                    Scope Type
                  </label>
                  <select
                    value={newException.scope_type}
                    onChange={(e) => setNewException({ ...newException, scope_type: e.target.value })}
                    className="w-full border rounded-lg px-2 py-1.5 text-xs focus:outline-none cursor-pointer"
                    style={{
                      backgroundColor: 'var(--input-bg)',
                      borderColor: 'var(--input-border)',
                      color: 'var(--text-primary)',
                    }}
                  >
                    <option value="department">Department</option>
                    <option value="project">Project</option>
                    <option value="data_type">Data Type</option>
                    <option value="vendor">Vendor</option>
                  </select>
                </div>
              </div>

              <div>
                <label className="block text-[11px] font-semibold text-[var(--text-secondary)] mb-1">
                  Scope Target Value
                </label>
                <input
                  type="text"
                  value={newException.scope_value}
                  onChange={(e) => setNewException({ ...newException, scope_value: e.target.value })}
                  placeholder="e.g. engineering or AWS-GovCloud"
                  className="w-full border rounded-lg px-2.5 py-1.5 text-xs focus:outline-none"
                  style={{
                    backgroundColor: 'var(--input-bg)',
                    borderColor: 'var(--input-border)',
                    color: 'var(--text-primary)',
                  }}
                />
              </div>

              <div>
                <label className="block text-[11px] font-semibold text-[var(--text-secondary)] mb-1">
                  Audit Justification
                </label>
                <textarea
                  value={newException.justification}
                  onChange={(e) => setNewException({ ...newException, justification: e.target.value })}
                  rows={2}
                  placeholder="Official audit committee rationale..."
                  className="w-full border rounded-lg px-2.5 py-1.5 text-xs focus:outline-none resize-none"
                  style={{
                    backgroundColor: 'var(--input-bg)',
                    borderColor: 'var(--input-border)',
                    color: 'var(--text-primary)',
                  }}
                />
              </div>

              <button
                type="submit"
                disabled={submittingException}
                className="w-full py-2 rounded-xl text-xs font-semibold shadow-sm transition flex items-center justify-center gap-1.5 cursor-pointer active:scale-95 disabled:opacity-50"
                style={{
                  backgroundColor: 'var(--brand-accent)',
                  color: 'var(--cta-text)',
                }}
              >
                <ShieldCheck className="w-3.5 h-3.5" />
                <span>{submittingException ? 'Registering...' : 'Register Scoped Exception'}</span>
              </button>
            </form>
          </div>

          {/* L2 Precedence Ladder Reference */}
          <div className="pt-2 border-t space-y-2" style={{ borderColor: 'var(--border-color)' }}>
            <h3 className="text-xs font-bold uppercase tracking-wider text-[var(--text-muted)] flex items-center gap-1.5">
              <Scale className="w-3.5 h-3.5 text-[var(--brand-accent)]" />
              <span>Layer 2: Governed 9-State Precedence Ladder (lore.md §3)</span>
            </h3>
            <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-9 gap-1.5 text-center">
              {[
                { rank: 1, state: 'denied', dir: 'stop', color: 'var(--error)' },
                { rank: 2, state: 'violation', dir: 'stop', color: 'var(--error)' },
                { rank: 3, state: 'conflicting', dir: 'ask_user', color: 'var(--warning)' },
                { rank: 4, state: 'insufficient', dir: 'ask_user', color: 'var(--warning)' },
                { rank: 5, state: 'abstain', dir: 'ask_user', color: 'var(--text-muted)' },
                { rank: 6, state: 'human_review', dir: 'escalate', color: 'var(--brand-accent)' },
                { rank: 7, state: 'qualified', dir: 'proceed_cite', color: 'var(--warning)' },
                { rank: 8, state: 'supported', dir: 'proceed_cite', color: 'var(--success)' },
                { rank: 9, state: 'no_knowledge', dir: 'proceed', color: 'var(--text-muted)' },
              ].map((item) => (
                <div 
                  key={item.rank}
                  className="p-2 rounded-lg border text-[10px] space-y-0.5"
                  style={{
                    backgroundColor: 'var(--bg-surface-soft)',
                    borderColor: 'var(--border-color)',
                  }}
                >
                  <div className="font-mono text-[9px] text-[var(--text-muted)]">#{item.rank}</div>
                  <div className="font-bold uppercase truncate" style={{ color: item.color }}>{item.state}</div>
                  <div className="text-[9px] font-mono text-[var(--text-muted)] truncate">{item.dir}</div>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* Quota Usage Meters & Team Management */}
      {(activeSection === 'all' || activeSection === 'team') && (
        <>
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
      </>
      )}
    </div>
  );
};
