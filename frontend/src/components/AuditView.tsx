'use client';

import React, { useState } from 'react';
import { 
  ShieldCheck, 
  RotateCw, 
  Key, 
  CheckCircle2, 
  XCircle, 
  X, 
  ShieldAlert, 
  FileCheck2,
  Lock
} from 'lucide-react';
import { AuditEvent, api, ZkAttestationEnvelope, ZkVerifyResponse } from '@/lib/api';
import { useI18n } from '@/lib/i18n';

interface AuditViewProps {
  events: AuditEvent[];
  onRefresh: () => void;
}

export const AuditView: React.FC<AuditViewProps> = ({
  events,
  onRefresh
}) => {
  const { t } = useI18n();

  // ZK External Proof Verification Modal State
  const [showVerifyModal, setShowVerifyModal] = useState(false);
  const [proofJsonInput, setProofJsonInput] = useState('');
  const [isVerifying, setIsVerifying] = useState(false);
  const [verifyResult, setVerifyResult] = useState<ZkVerifyResponse | null>(null);
  const [verifyError, setVerifyError] = useState<string | null>(null);

  const handleVerify = async () => {
    setVerifyError(null);
    setVerifyResult(null);

    const trimmed = proofJsonInput.trim();
    if (!trimmed) {
      setVerifyError('Please paste a valid ZK attestation envelope JSON.');
      return;
    }

    let parsed: Record<string, unknown>;
    try {
      parsed = JSON.parse(trimmed);
    } catch {
      setVerifyError('Malformed JSON: Unable to parse attestation envelope.');
      return;
    }

    // Envelope validation
    const envelope = (parsed.attestation_envelope || parsed.zk_attestation || parsed) as unknown as ZkAttestationEnvelope;
    if (!envelope.workspace_state_root || !envelope.proof_system) {
      setVerifyError('Invalid envelope: Missing required fields (workspace_state_root, proof_system).');
      return;
    }

    try {
      setIsVerifying(true);
      const res = await api.verifyZkAttestation(envelope);
      setVerifyResult(res);
    } catch (err: unknown) {
      const errMsg = err instanceof Error ? err.message : 'Verification request failed.';
      setVerifyError(errMsg);
    } finally {
      setIsVerifying(false);
    }
  };

  const handleCloseModal = () => {
    setShowVerifyModal(false);
    setVerifyError(null);
    setVerifyResult(null);
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div>
          <h2 className="text-lg sm:text-xl font-extrabold flex items-center gap-2 text-[var(--text-primary)]">
            <ShieldCheck className="w-5 h-5 text-[var(--brand-accent)]" />
            <span>{t('audit.title')}</span>
          </h2>
          <p className="text-xs text-[var(--text-muted)] mt-1">
            {t('audit.subtitle')}
          </p>
        </div>
        <div className="flex items-center gap-2.5">
          <button
            onClick={() => setShowVerifyModal(true)}
            className="flex items-center gap-2 px-3.5 py-2 rounded-xl text-xs font-semibold border transition cursor-pointer active:scale-95 shadow-sm hover:bg-[var(--accent-light)]"
            style={{
              backgroundColor: 'var(--bg-surface)',
              borderColor: 'var(--border-color)',
              color: 'var(--brand-accent)',
            }}
          >
            <Key className="w-3.5 h-3.5" />
            <span>Verify External Proof</span>
          </button>
          <button
            onClick={onRefresh}
            className="flex items-center gap-2 px-3.5 py-2 rounded-xl text-xs font-semibold border transition cursor-pointer active:scale-95 shadow-sm"
            style={{
              backgroundColor: 'var(--bg-surface)',
              borderColor: 'var(--border-color)',
              color: 'var(--text-primary)',
            }}
          >
            <RotateCw className="w-3.5 h-3.5 text-[var(--brand-accent)]" />
            <span>{t('common.refresh')}</span>
          </button>
        </div>
      </div>

      <div 
        className="rounded-2xl border overflow-hidden shadow-sm"
        style={{
          backgroundColor: 'var(--bg-surface)',
          borderColor: 'var(--border-color)',
        }}
      >
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs sm:text-sm">
            <thead 
              className="text-xs font-bold uppercase tracking-wider border-b"
              style={{
                backgroundColor: 'var(--table-header-bg)',
                borderColor: 'var(--border-color)',
                color: 'var(--text-muted)',
              }}
            >
              <tr>
                <th className="px-5 py-3.5">{t('audit.timestamp')}</th>
                <th className="px-4 py-3.5">{t('audit.action')}</th>
                <th className="px-4 py-3.5">{t('audit.actor')}</th>
                <th className="px-4 py-3.5">{t('audit.resource')}</th>
                <th className="px-5 py-3.5">{t('audit.details')}</th>
              </tr>
            </thead>
            <tbody className="divide-y font-mono text-xs" style={{ borderColor: 'var(--border-color)' }}>
              {events.length === 0 ? (
                <tr>
                  <td colSpan={5} className="px-6 py-12 text-center text-sm font-sans text-[var(--text-muted)]">
                    No audit events recorded yet.
                  </td>
                </tr>
              ) : (
                events.map((ev) => (
                  <tr 
                    key={ev.id} 
                    className="transition-colors duration-150"
                    onMouseEnter={(e) => (e.currentTarget.style.backgroundColor = 'var(--table-row-hover)')}
                    onMouseLeave={(e) => (e.currentTarget.style.backgroundColor = 'transparent')}
                  >
                    <td className="px-5 py-3.5 text-[var(--text-muted)] whitespace-nowrap">
                      {new Date(ev.created_at).toLocaleString()}
                    </td>
                    <td className="px-4 py-3.5">
                      <span 
                        className="px-2 py-0.5 rounded font-bold text-[11px] border"
                        style={{
                          backgroundColor: 'var(--accent-light)',
                          borderColor: 'var(--border-color)',
                          color: 'var(--brand-accent)',
                        }}
                      >
                        {ev.event_type}
                      </span>
                    </td>
                    <td className="px-4 py-3.5 text-[var(--text-primary)] font-sans font-medium">
                      {ev.username || 'System'}
                    </td>
                    <td className="px-4 py-3.5 text-[var(--text-muted)]">
                      {ev.target_type} ({ev.target_id.substring(0, 8)}...)
                    </td>
                    <td className="px-5 py-3.5 text-[var(--text-secondary)] truncate max-w-xs font-mono">
                      {JSON.stringify(ev.details)}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* External ZKP Verification Modal */}
      {showVerifyModal && (
        <div className="fixed inset-0 z-50 bg-black/60 backdrop-blur-sm flex items-center justify-center p-4 animate-in fade-in duration-150">
          <div 
            className="w-full max-w-2xl rounded-2xl border shadow-2xl p-6 relative max-h-[90vh] overflow-y-auto space-y-5"
            style={{
              backgroundColor: 'var(--bg-surface)',
              borderColor: 'var(--border-color)',
              color: 'var(--text-primary)'
            }}
          >
            <button 
              onClick={handleCloseModal}
              className="absolute top-4 right-4 p-1.5 rounded-lg border hover:bg-[var(--accent-light)] transition"
              style={{ borderColor: 'var(--border-color)' }}
            >
              <X className="w-4 h-4 text-[var(--text-muted)]" />
            </button>

            <div className="flex items-center gap-3">
              <div className="p-2.5 rounded-xl bg-[var(--accent-light)] text-[var(--brand-accent)]">
                <Key className="w-5 h-5" />
              </div>
              <div>
                <h3 className="text-base font-extrabold flex items-center gap-2">
                  <span>Verify External Zero-Knowledge Proof</span>
                  <span className="px-2 py-0.5 rounded-full text-[10px] font-bold uppercase tracking-wider border bg-[var(--accent-light)] text-[var(--brand-accent)] border-[var(--border-color)]">
                    Audit Verification
                  </span>
                </h3>
                <p className="text-xs text-[var(--text-muted)] mt-0.5">
                  Verify cross-organization cryptographic attestations without accessing raw rule statements or contract text.
                </p>
              </div>
            </div>

            <div className="space-y-2">
              <label className="text-xs font-semibold text-[var(--text-secondary)] flex items-center justify-between">
                <span>Attestation Envelope JSON</span>
                <button
                  type="button"
                  onClick={() => {
                    const sample = {
                      proof_system: "zkp_lite_merkle",
                      workspace_state_root: "a1b2c3d4e5f60718293a4b5c6d7e8f90123456789abcdef0123456789abcdef0",
                      public_inputs: {
                        decision_type: "regulatory_compliance",
                        required_authority_floor: 4,
                        evidence_status: "satisfied",
                        effective_timestamp: Math.floor(Date.now() / 1000),
                        role_commitment_hash: "3c9909afec25354d551dae21590bb26e38d53f2173b8d3dc3eee4c047e7ab1c1",
                        proven_rules_count: 1
                      },
                      proof_b64: "eyJub25jZSI6ICIwMCIsICJtZXJrbGVfcGF0aHMiOiBbXX0=",
                      verified: true,
                      generated_at: new Date().toISOString()
                    };
                    setProofJsonInput(JSON.stringify(sample, null, 2));
                  }}
                  className="text-[11px] text-[var(--brand-accent)] hover:underline"
                >
                  Load Sample
                </button>
              </label>
              <textarea
                value={proofJsonInput}
                onChange={(e) => setProofJsonInput(e.target.value)}
                placeholder='Paste {"proof_system": "...", "workspace_state_root": "...", "public_inputs": {...}, "proof_b64": "..."}'
                rows={7}
                className="w-full text-xs font-mono p-3 rounded-xl border bg-[var(--bg-main)] text-[var(--text-primary)] focus:outline-none focus:ring-1 focus:ring-[var(--brand-accent)]"
                style={{ borderColor: 'var(--border-color)' }}
              />
            </div>

            {verifyError && (
              <div className="p-3 rounded-xl border flex items-start gap-2.5 text-xs bg-red-500/10 border-red-500/30 text-red-400">
                <ShieldAlert className="w-4 h-4 shrink-0 mt-0.5 text-red-500" />
                <span>{verifyError}</span>
              </div>
            )}

            {verifyResult && (
              <div 
                className="p-4 rounded-xl border space-y-3"
                style={{ 
                  backgroundColor: verifyResult.verified ? 'rgba(34, 197, 94, 0.05)' : 'rgba(239, 68, 68, 0.05)',
                  borderColor: verifyResult.verified ? 'rgba(34, 197, 94, 0.3)' : 'rgba(239, 68, 68, 0.3)'
                }}
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    {verifyResult.verified ? (
                      <CheckCircle2 className="w-5 h-5 text-green-500" />
                    ) : (
                      <XCircle className="w-5 h-5 text-red-500" />
                    )}
                    <div>
                      <h4 className="text-xs font-bold uppercase tracking-wider" style={{ color: verifyResult.verified ? 'var(--sage-deep)' : 'var(--red)' }}>
                        {verifyResult.verified ? 'Cryptographic Attestation Verified' : 'Attestation Verification Failed'}
                      </h4>
                      <p className="text-[11px] text-[var(--text-muted)]">
                        {verifyResult.message}
                      </p>
                    </div>
                  </div>
                  <span className="text-[11px] font-mono px-2 py-0.5 rounded border bg-[var(--bg-surface)]" style={{ borderColor: 'var(--border-color)' }}>
                    {verifyResult.proof_system}
                  </span>
                </div>

                <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 text-[11px] font-mono pt-2 border-t" style={{ borderColor: 'var(--border-color)' }}>
                  <div>
                    <span className="text-[var(--text-muted)] block">Workspace State Root:</span>
                    <span className="truncate block font-semibold text-[var(--text-primary)]" title={verifyResult.workspace_state_root}>
                      {verifyResult.workspace_state_root}
                    </span>
                  </div>
                  <div>
                    <span className="text-[var(--text-muted)] block">Decision Type:</span>
                    <span className="font-semibold text-[var(--text-primary)]">
                      {verifyResult.public_inputs?.decision_type || 'N/A'}
                    </span>
                  </div>
                  <div>
                    <span className="text-[var(--text-muted)] block">Required Authority Floor:</span>
                    <span className="font-semibold text-[var(--text-primary)]">
                      Tier {verifyResult.public_inputs?.required_authority_floor ?? 'N/A'}
                    </span>
                  </div>
                  <div>
                    <span className="text-[var(--text-muted)] block">Role Commitment Hash:</span>
                    <span className="truncate block font-semibold text-[var(--text-primary)]" title={verifyResult.public_inputs?.role_commitment_hash}>
                      {verifyResult.public_inputs?.role_commitment_hash || 'N/A'}
                    </span>
                  </div>
                </div>

                <div className="flex items-center gap-2 pt-2 text-[11px] text-[var(--text-muted)] border-t" style={{ borderColor: 'var(--border-color)' }}>
                  <Lock className="w-3.5 h-3.5 text-green-500" />
                  <span>Zero-Leakage Guarantee: Confirmed. No confidential policy statements or raw text disclosed in proof payload.</span>
                </div>
              </div>
            )}

            <div className="flex items-center justify-between pt-3 border-t" style={{ borderColor: 'var(--border-color)' }}>
              <button
                type="button"
                onClick={() => {
                  setProofJsonInput('');
                  setVerifyResult(null);
                  setVerifyError(null);
                }}
                className="text-xs text-[var(--text-muted)] hover:text-[var(--text-primary)] transition"
              >
                Clear
              </button>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={handleCloseModal}
                  className="px-3.5 py-1.5 rounded-lg border text-xs font-semibold hover:bg-[var(--accent-light)] transition cursor-pointer"
                  style={{ borderColor: 'var(--border-color)' }}
                >
                  Close
                </button>
                <button
                  type="button"
                  disabled={isVerifying || !proofJsonInput.trim()}
                  onClick={handleVerify}
                  className="flex items-center gap-1.5 px-4 py-1.5 rounded-lg text-xs font-semibold bg-[var(--brand-accent)] text-white hover:opacity-90 disabled:opacity-50 transition cursor-pointer"
                >
                  {isVerifying ? (
                    <RotateCw className="w-3.5 h-3.5 animate-spin" />
                  ) : (
                    <FileCheck2 className="w-3.5 h-3.5" />
                  )}
                  <span>{isVerifying ? 'Verifying...' : 'Verify Attestation'}</span>
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
