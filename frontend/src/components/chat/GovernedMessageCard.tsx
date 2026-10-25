'use client';

import React, { useState } from 'react';
import { 
  User, 
  Sparkles, 
  ShieldCheck, 
  CheckCircle2, 
  Scale, 
  AlertTriangle, 
  Clock, 
  FileText, 
  ShieldAlert, 
  Cpu, 
  ChevronDown, 
  ChevronUp, 
  Quote, 
  Shield, 
  Layers, 
  RotateCcw,
  AlertCircle,
  FileCheck,
  Activity,
  Key
} from 'lucide-react';
import { ChatMessage, Citation } from '@/lib/api';

interface GovernedMessageCardProps {
  message: ChatMessage;
  onRetry?: (query: string) => void;
  language?: 'en' | 'bn';
}

export const GovernedMessageCard: React.FC<GovernedMessageCardProps> = ({
  message,
  onRetry,
  language = 'en'
}) => {
  const [showEvidenceDetails, setShowEvidenceDetails] = useState(false);
  const [showLayersInspector, setShowLayersInspector] = useState(false);

  // Helper for Status Badge
  const getStateBadge = (state?: string, directive?: string) => {
    const s = (state || 'unknown').toLowerCase();
    const d = (directive || 'proceed').toUpperCase();

    switch (s) {
      case 'supported':
        return (
          <div className="flex items-center gap-1.5 flex-wrap">
            <span 
              className="px-2.5 py-0.8 rounded-full text-[11px] font-bold uppercase tracking-wider border flex items-center gap-1.5"
              style={{
                backgroundColor: 'var(--success-bg)',
                borderColor: 'var(--border-color)',
                color: 'var(--success)',
              }}
            >
              <CheckCircle2 className="w-3.5 h-3.5" />
              <span>SUPPORTED</span>
            </span>
            <span 
              className="text-[10px] font-mono font-semibold px-2 py-0.5 rounded border"
              style={{
                backgroundColor: 'var(--accent-light)',
                borderColor: 'var(--border-color)',
                color: 'var(--brand-accent)',
              }}
            >
              DIRECTIVE: {d}
            </span>
          </div>
        );
      case 'qualified':
        return (
          <div className="flex items-center gap-1.5 flex-wrap">
            <span 
              className="px-2.5 py-0.8 rounded-full text-[11px] font-bold uppercase tracking-wider border flex items-center gap-1.5"
              style={{
                backgroundColor: 'var(--warning-bg)',
                borderColor: 'var(--border-color)',
                color: 'var(--warning)',
              }}
            >
              <Scale className="w-3.5 h-3.5" />
              <span>QUALIFIED BY GOVERNANCE</span>
            </span>
            <span 
              className="text-[10px] font-mono font-semibold px-2 py-0.5 rounded border"
              style={{
                backgroundColor: 'var(--warning-bg)',
                borderColor: 'var(--border-color)',
                color: 'var(--warning)',
              }}
            >
              DIRECTIVE: {d}
            </span>
          </div>
        );
      case 'insufficient':
        return (
          <div className="flex items-center gap-1.5 flex-wrap">
            <span 
              className="px-2.5 py-0.8 rounded-full text-[11px] font-bold uppercase tracking-wider border flex items-center gap-1.5"
              style={{
                backgroundColor: 'var(--error-bg)',
                borderColor: 'var(--border-color)',
                color: 'var(--error)',
              }}
            >
              <AlertTriangle className="w-3.5 h-3.5" />
              <span>INSUFFICIENT EVIDENCE</span>
            </span>
            <span 
              className="text-[10px] font-mono font-semibold px-2 py-0.5 rounded border"
              style={{
                backgroundColor: 'var(--error-bg)',
                borderColor: 'var(--border-color)',
                color: 'var(--error)',
              }}
            >
              DIRECTIVE: {d}
            </span>
          </div>
        );
      case 'conflicting':
        return (
          <div className="flex items-center gap-1.5 flex-wrap">
            <span 
              className="px-2.5 py-0.8 rounded-full text-[11px] font-bold uppercase tracking-wider border flex items-center gap-1.5"
              style={{
                backgroundColor: 'var(--warning-bg)',
                borderColor: 'var(--border-color)',
                color: 'var(--warning)',
              }}
            >
              <Scale className="w-3.5 h-3.5" />
              <span>CONFLICT DETECTED</span>
            </span>
            <span 
              className="text-[10px] font-mono font-semibold px-2 py-0.5 rounded border"
              style={{
                backgroundColor: 'var(--warning-bg)',
                borderColor: 'var(--border-color)',
                color: 'var(--warning)',
              }}
            >
              DIRECTIVE: {d}
            </span>
          </div>
        );
      case 'denied':
        return (
          <div className="flex items-center gap-1.5 flex-wrap">
            <span 
              className="px-2.5 py-0.8 rounded-full text-[11px] font-bold uppercase tracking-wider border flex items-center gap-1.5"
              style={{
                backgroundColor: 'var(--error-bg)',
                borderColor: 'var(--border-color)',
                color: 'var(--error)',
              }}
            >
              <ShieldAlert className="w-3.5 h-3.5" />
              <span>ACCESS DENIED</span>
            </span>
            <span 
              className="text-[10px] font-mono font-semibold px-2 py-0.5 rounded border"
              style={{
                backgroundColor: 'var(--error-bg)',
                borderColor: 'var(--border-color)',
                color: 'var(--error)',
              }}
            >
              DIRECTIVE: {d}
            </span>
          </div>
        );
      default:
        return (
          <span 
            className="px-2.5 py-0.8 rounded-full text-[11px] font-mono uppercase tracking-wider border"
            style={{
              backgroundColor: 'var(--bg-surface-soft)',
              borderColor: 'var(--border-color)',
              color: 'var(--text-secondary)',
            }}
          >
            {s} • {d}
          </span>
        );
    }
  };

  const getDocumentStatusBadge = (status?: string) => {
    const norm = (status || 'unknown').toLowerCase();
    switch (norm) {
      case 'approved':
        return (
          <span className="px-2 py-0.5 rounded-full text-[10px] font-bold uppercase tracking-wider border flex items-center gap-1 bg-[var(--success-bg)] border-[var(--border-color)] text-[var(--success)]">
            <CheckCircle2 className="w-3 h-3" />
            <span>Approved</span>
          </span>
        );
      case 'draft':
        return (
          <span className="px-2 py-0.5 rounded-full text-[10px] font-bold uppercase tracking-wider border flex items-center gap-1 bg-[var(--warning-bg)] border-[var(--border-color)] text-[var(--warning)]">
            <AlertTriangle className="w-3 h-3" />
            <span>Draft</span>
          </span>
        );
      case 'future-effective':
        return (
          <span className="px-2 py-0.5 rounded-full text-[10px] font-bold uppercase tracking-wider border flex items-center gap-1 bg-[var(--accent-light)] border-[var(--border-color)] text-[var(--brand-accent)]">
            <Clock className="w-3 h-3" />
            <span>Future-Effective</span>
          </span>
        );
      case 'superseded':
        return (
          <span className="px-2 py-0.5 rounded-full text-[10px] font-bold uppercase tracking-wider border flex items-center gap-1 bg-[var(--error-bg)] border-[var(--border-color)] text-[var(--error)]">
            <Scale className="w-3 h-3" />
            <span>Superseded</span>
          </span>
        );
      default:
        return (
          <span className="px-2 py-0.5 rounded-full text-[10px] font-bold uppercase tracking-wider border flex items-center gap-1 bg-[var(--bg-surface-soft)] border-[var(--border-color)] text-[var(--text-secondary)]">
            <span>{norm}</span>
          </span>
        );
    }
  };

  const getEvidenceTypeBadge = (evidenceType?: string) => {
    if (evidenceType === 'direct') {
      return (
        <span className="px-2 py-0.5 rounded text-[10px] font-mono font-bold uppercase border flex items-center gap-1 bg-[var(--accent-light)] border-[var(--border-color)] text-[var(--brand-accent)]">
          <ShieldCheck className="w-3 h-3" />
          <span>Direct Evidence</span>
        </span>
      );
    }
    return (
      <span className="px-2 py-0.5 rounded text-[10px] font-mono font-bold uppercase border flex items-center gap-1 bg-[var(--bg-surface-soft)] border-[var(--border-color)] text-[var(--text-secondary)]">
        <Scale className="w-3 h-3" />
        <span>Inference</span>
      </span>
    );
  };

  // Safe formatting for timestamp
  const formatTime = (isoString?: string) => {
    if (!isoString) return '';
    try {
      return new Date(isoString).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    } catch (e) {
      return '';
    }
  };

  // Render User Message
  if (message.role === 'user') {
    return (
      <div className="flex justify-end my-3">
        <div 
          className="max-w-[85%] sm:max-w-[75%] rounded-2xl rounded-tr-sm p-4 border shadow-xs space-y-1.5 transition-all"
          style={{
            backgroundColor: 'var(--accent-light)',
            borderColor: 'var(--brand-accent)',
          }}
        >
          <div className="flex items-center justify-between gap-3 text-[11px] font-mono pb-1 border-b border-[var(--brand-accent)]/20">
            <span className="font-bold text-[var(--brand-accent)] flex items-center gap-1.5">
              <User className="w-3.5 h-3.5" />
              You
            </span>
            <span className="text-[var(--text-muted)] text-[10px]">
              {formatTime(message.created_at)}
            </span>
          </div>

          <p className="text-xs sm:text-sm font-medium text-[var(--text-primary)] leading-relaxed whitespace-pre-wrap">
            {message.content}
          </p>
        </div>
      </div>
    );
  }

  // Render Failed Turn
  if (message.status === 'failed') {
    return (
      <div className="flex justify-start my-3">
        <div 
          className="w-full max-w-3xl rounded-2xl p-4 border space-y-2 shadow-xs"
          style={{
            backgroundColor: 'var(--error-bg)',
            borderColor: 'var(--border-color)',
            color: 'var(--error)',
          }}
        >
          <div className="flex items-center justify-between">
            <span className="text-xs font-bold uppercase tracking-wider flex items-center gap-1.5">
              <AlertCircle className="w-4 h-4" />
              Governed Query Failed
            </span>
            <span className="text-[10px] font-mono">{formatTime(message.created_at)}</span>
          </div>
          <p className="text-xs leading-relaxed font-mono">
            {message.error_message || 'The model or retrieval service encountered an unrecoverable failure.'}
          </p>
          {onRetry && (
            <div className="pt-1">
              <button
                onClick={() => onRetry(message.content)}
                className="px-3 py-1.5 rounded-xl text-xs font-semibold border flex items-center gap-1.5 transition cursor-pointer active:scale-95 bg-[var(--bg-surface)] text-[var(--text-primary)] border-[var(--border-color)]"
              >
                <RotateCcw className="w-3 h-3 text-[var(--brand-accent)]" />
                <span>Retry Turn</span>
              </button>
            </div>
          )}
        </div>
      </div>
    );
  }

  // Render Assistant Message with full LORE Governed fidelity
  const effectiveCitations: Citation[] = message.revalidated_citations || message.citations || [];
  const layersBreakdown = message.layers_breakdown;

  return (
    <div className="flex justify-start my-4">
      <div 
        className="w-full rounded-2xl p-4 sm:p-5 border shadow-sm space-y-4 transition-all duration-200"
        style={{
          backgroundColor: 'var(--bg-surface)',
          borderColor: 'var(--border-color)',
        }}
      >
        {/* Top Header: LORE Governance State & Metadata */}
        <div 
          className="flex flex-col sm:flex-row sm:items-center justify-between gap-2.5 border-b pb-3"
          style={{ borderColor: 'var(--border-color)' }}
        >
          <div className="flex items-center gap-2 flex-wrap">
            {getStateBadge(message.governance_state, message.governance_directive)}
            <span 
              className="px-2 py-0.5 rounded text-[10px] font-mono font-semibold border flex items-center gap-1"
              style={{
                backgroundColor: 'var(--bg-surface-soft)',
                borderColor: 'var(--border-color)',
                color: 'var(--brand-accent)',
              }}
            >
              <Cpu className="w-3 h-3 text-[var(--brand-accent)]" />
              LORE Governed Engine
            </span>
          </div>

          <div className="flex items-center gap-2 text-xs font-mono text-[var(--text-muted)]">
            {message.trace_id && (
              <span className="hidden sm:inline text-[10px]">
                Trace: {message.trace_id.slice(0, 12)}...
              </span>
            )}
            <span 
              className="px-2 py-0.5 rounded-full text-[10px] font-semibold border flex items-center gap-1"
              style={{
                backgroundColor: 'var(--accent-light)',
                borderColor: 'var(--border-color)',
                color: 'var(--brand-accent)',
              }}
            >
              <ShieldCheck className="w-3 h-3" />
              Anti-Hallucination Verified
            </span>
            <span className="text-[10px]">{formatTime(message.created_at)}</span>
          </div>
        </div>

        {/* Answer Narrative */}
        <div 
          className="p-4 rounded-xl border leading-relaxed text-xs sm:text-sm whitespace-pre-line shadow-xs"
          style={{
            backgroundColor: 'var(--bg-surface-soft)',
            borderColor: 'var(--border-color)',
            color: 'var(--text-primary)',
          }}
        >
          <div className="font-bold text-xs uppercase tracking-wider text-[var(--brand-accent)] mb-1.5 flex items-center gap-2">
            <CheckCircle2 className="w-4 h-4 text-[var(--brand-accent)]" />
            <span>Governed Decision & Answer</span>
          </div>
          <div className="text-sm font-medium leading-relaxed">
            {message.content}
          </div>
        </div>

        {/* Proof Details Toggle */}
        <div className="flex items-center justify-between pt-1">
          <button
            type="button"
            onClick={() => setShowEvidenceDetails(!showEvidenceDetails)}
            className="px-3.5 py-2 rounded-xl text-xs font-bold border flex items-center gap-2 transition cursor-pointer active:scale-95"
            style={{
              backgroundColor: showEvidenceDetails ? 'var(--accent-light)' : 'var(--bg-surface-soft)',
              borderColor: showEvidenceDetails ? 'var(--brand-accent)' : 'var(--border-color)',
              color: showEvidenceDetails ? 'var(--brand-accent)' : 'var(--text-primary)',
            }}
          >
            <ShieldCheck className="w-3.5 h-3.5 text-[var(--brand-accent)]" />
            <span>{showEvidenceDetails ? 'Hide details & proof' : 'Show details & proof'}</span>
            <span 
              className="text-[10px] font-mono px-1.5 py-0.2 rounded border"
              style={{
                backgroundColor: 'var(--bg-surface)',
                borderColor: 'var(--border-color)',
                color: 'var(--text-muted)',
              }}
            >
              {effectiveCitations.length} {effectiveCitations.length === 1 ? 'source' : 'sources'}
            </span>
            {showEvidenceDetails ? (
              <ChevronUp className="w-3.5 h-3.5 text-[var(--brand-accent)]" />
            ) : (
              <ChevronDown className="w-3.5 h-3.5 text-[var(--text-muted)]" />
            )}
          </button>

          {layersBreakdown && (
            <button
              type="button"
              onClick={() => setShowLayersInspector(!showLayersInspector)}
              className="text-xs font-semibold px-2.5 py-1.5 rounded-lg border flex items-center gap-1.5 text-[var(--text-secondary)] hover:text-[var(--brand-accent)] transition cursor-pointer"
              style={{
                backgroundColor: showLayersInspector ? 'var(--accent-light)' : 'transparent',
                borderColor: showLayersInspector ? 'var(--brand-accent)' : 'var(--border-color)',
              }}
            >
              <Layers className="w-3.5 h-3.5 text-[var(--brand-accent)]" />
              <span>Layers</span>
              {showLayersInspector ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
            </button>
          )}
        </div>

        {/* Citations and Evidence Breakdown */}
        {showEvidenceDetails && (
          <div 
            className="space-y-4 pt-3 border-t transition-all duration-200"
            style={{ borderColor: 'var(--border-color)' }}
          >
            <div className="flex items-center justify-between">
              <div className="text-xs font-bold text-[var(--text-muted)] uppercase tracking-wider flex items-center gap-1.5">
                <Quote className="w-3.5 h-3.5 text-[var(--brand-accent)]" />
                <span>Authoritative Proof Citations ({effectiveCitations.length})</span>
              </div>
              <span className="text-[10px] font-mono text-[var(--text-muted)]">
                Audit Lineage Verified
              </span>
            </div>

            {effectiveCitations.length === 0 ? (
              <div 
                className="p-3.5 rounded-xl border text-xs text-center space-y-1"
                style={{
                  backgroundColor: 'var(--bg-surface-soft)',
                  borderColor: 'var(--border-color)',
                  color: 'var(--text-muted)',
                }}
              >
                <Shield className="w-4 h-4 mx-auto text-[var(--brand-accent)] mb-1" />
                <div className="font-semibold text-[var(--text-secondary)]">No Evidence Disclosed</div>
                <div>Access restrictions prohibit source exposure or no authoritative records were cited.</div>
              </div>
            ) : (
              <div className="grid grid-cols-1 gap-2.5">
                {effectiveCitations.map((cit, idx) => {
                  const isInaccessible = (cit as any).is_inaccessible || false;

                  return (
                    <div 
                      key={cit.citation_id || idx}
                      className="p-3.5 rounded-xl border space-y-2.5 text-xs shadow-xs"
                      style={{
                        backgroundColor: 'var(--bg-surface-soft)',
                        borderColor: 'var(--border-color)',
                      }}
                    >
                      {/* Document Title & Status */}
                      <div 
                        className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 border-b pb-2"
                        style={{ borderColor: 'var(--border-color)' }}
                      >
                        <div className="flex items-center gap-2 flex-wrap">
                          <FileText className="w-3.5 h-3.5 text-[var(--brand-accent)] shrink-0" />
                          <span className="font-bold text-xs sm:text-sm text-[var(--text-primary)]">
                            {cit.document_title}
                          </span>
                          <span 
                            className="text-[10px] font-mono px-1.5 py-0.2 rounded border"
                            style={{
                              backgroundColor: 'var(--bg-surface)',
                              borderColor: 'var(--border-color)',
                              color: 'var(--text-muted)',
                            }}
                          >
                            ID: {cit.document_id?.slice(0, 8)}...
                          </span>
                        </div>

                        <div className="flex items-center gap-1.5 flex-wrap">
                          {getDocumentStatusBadge(cit.document_status)}
                          {getEvidenceTypeBadge(cit.evidence_type)}
                        </div>
                      </div>

                      {/* Redacted Inaccessible Warning if Document subsequently Deleted */}
                      {isInaccessible && (
                        <div 
                          className="p-2 rounded-lg border text-xs flex items-center gap-2"
                          style={{
                            backgroundColor: 'var(--warning-bg)',
                            borderColor: 'var(--border-color)',
                            color: 'var(--warning)',
                          }}
                        >
                          <AlertTriangle className="w-3.5 h-3.5 shrink-0" />
                          <span className="font-semibold">
                            Source document has been archived or removed from workspace. Quoted text is protected/redacted.
                          </span>
                        </div>
                      )}

                      {/* Passage proof */}
                      <div className="space-y-1">
                        <div className="text-[10px] font-bold uppercase tracking-wider text-[var(--text-muted)] flex items-center gap-1">
                          <CheckCircle2 className="w-3 h-3 text-[var(--success)]" />
                          <span>Source Proof Passage:</span>
                        </div>
                        <blockquote 
                          className="text-xs italic font-medium pl-3 py-1.5 border-l-2 leading-relaxed text-[var(--text-primary)] rounded-r-lg"
                          style={{
                            borderColor: 'var(--brand-accent)',
                            backgroundColor: 'var(--bg-surface)',
                          }}
                        >
                          &quot;{cit.shortest_passage || cit.passage}&quot;
                        </blockquote>
                      </div>

                      {/* Rank & Section */}
                      <div className="flex items-center gap-2 flex-wrap text-[10px] font-mono text-[var(--text-muted)]">
                        {cit.page_number != null && <span>Page {cit.page_number}</span>}
                        {cit.section && <span>• Section: {cit.section}</span>}
                        <span>• Authority Rank {cit.authority_level}</span>
                      </div>
                    </div>
                  );
                })}
              </div>
            )}

            {/* Mandatory Evidence Deficit (L3) */}
            {message.evidence_missing && message.evidence_missing.length > 0 && (
              <div 
                className="p-3.5 rounded-xl border space-y-1.5"
                style={{
                  backgroundColor: 'var(--error-bg)',
                  borderColor: 'var(--border-color)',
                }}
              >
                <div className="text-xs font-bold text-[var(--error)] uppercase tracking-wider flex items-center gap-1.5">
                  <AlertTriangle className="w-3.5 h-3.5" />
                  <span>Mandatory Evidence Deficit (LORE L3)</span>
                </div>
                {message.evidence_missing.map((me, idx) => (
                  <div key={idx} className="text-xs flex items-start gap-1.5 text-[var(--text-primary)]">
                    <span className="font-mono font-bold text-[var(--error)]">• [{me.requirement}]:</span>
                    <span>{me.explanation || (me as any).description || 'Required by policy checklist'}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* Governance Layers Breakdown Inspector */}
        {showLayersInspector && layersBreakdown && (
          <div 
            className="pt-3 border-t space-y-3 transition-all duration-200"
            style={{ borderColor: 'var(--border-color)' }}
          >
            <div className="flex items-center gap-2">
              <Layers className="w-4 h-4 text-[var(--brand-accent)]" />
              <span className="text-xs font-bold text-[var(--text-primary)] uppercase tracking-wider">
                Full 8-Layer Governance Evaluation Ledger
              </span>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-2 text-xs">
              {/* L7 */}
              <div className="p-2.5 rounded-xl border bg-[var(--bg-surface)] space-y-1" style={{ borderColor: 'var(--border-color)' }}>
                <div className="flex items-center justify-between">
                  <span className="text-[10px] font-mono font-bold text-[var(--brand-accent)]">L7: PERMISSION</span>
                  <span className={`text-[10px] font-bold px-1.5 py-0.2 rounded ${layersBreakdown.l7_permission?.status === 'passed' ? 'text-[var(--success)] bg-[var(--success-bg)]' : 'text-[var(--error)] bg-[var(--error-bg)]'}`}>
                    {layersBreakdown.l7_permission?.status?.toUpperCase() || 'PASSED'}
                  </span>
                </div>
                <p className="text-[11px] text-[var(--text-secondary)]">Multi-tenant isolation & ACL clearance</p>
              </div>

              {/* L6 */}
              <div className="p-2.5 rounded-xl border bg-[var(--bg-surface)] space-y-1" style={{ borderColor: 'var(--border-color)' }}>
                <div className="flex items-center justify-between">
                  <span className="text-[10px] font-mono font-bold text-[var(--brand-accent)]">L6: AUTHORITY</span>
                  <span className="text-[10px] font-bold px-1.5 py-0.2 rounded text-[var(--brand-accent)] bg-[var(--accent-light)]">
                    {layersBreakdown.l6_authority?.conflicts_count ? `${layersBreakdown.l6_authority.conflicts_count} RESOLVED` : 'NO CONFLICTS'}
                  </span>
                </div>
                <p className="text-[11px] text-[var(--text-secondary)]">Authority dominance & supersession</p>
              </div>

              {/* L5 */}
              <div className="p-2.5 rounded-xl border bg-[var(--bg-surface)] space-y-1" style={{ borderColor: 'var(--border-color)' }}>
                <div className="flex items-center justify-between">
                  <span className="text-[10px] font-mono font-bold text-[var(--brand-accent)]">L5: TEMPORAL</span>
                  <span className="text-[10px] font-bold px-1.5 py-0.2 rounded text-[var(--success)] bg-[var(--success-bg)]">
                    CURRENT
                  </span>
                </div>
                <p className="text-[11px] text-[var(--text-secondary)]">Effective date point-in-time checks</p>
              </div>

              {/* L3 */}
              <div className="p-2.5 rounded-xl border bg-[var(--bg-surface)] space-y-1" style={{ borderColor: 'var(--border-color)' }}>
                <div className="flex items-center justify-between">
                  <span className="text-[10px] font-mono font-bold text-[var(--brand-accent)]">L3: SUFFICIENCY</span>
                  <span className={`text-[10px] font-bold px-1.5 py-0.2 rounded ${layersBreakdown.l3_sufficiency?.is_sufficient ? 'text-[var(--success)] bg-[var(--success-bg)]' : 'text-[var(--error)] bg-[var(--error-bg)]'}`}>
                    {layersBreakdown.l3_sufficiency?.is_sufficient ? 'SATISFIED' : 'DEFICIT'}
                  </span>
                </div>
                <p className="text-[11px] text-[var(--text-secondary)]">Mandatory checklist completeness</p>
              </div>

              {/* L2 */}
              <div className="p-2.5 rounded-xl border bg-[var(--bg-surface)] space-y-1" style={{ borderColor: 'var(--border-color)' }}>
                <div className="flex items-center justify-between">
                  <span className="text-[10px] font-mono font-bold text-[var(--brand-accent)]">L2: ANSWER STATE</span>
                  <span className="text-[10px] font-bold px-1.5 py-0.2 rounded text-[var(--brand-accent)] bg-[var(--accent-light)]">
                    {layersBreakdown.l2_answer_state?.final_state?.toUpperCase() || 'SUPPORTED'}
                  </span>
                </div>
                <p className="text-[11px] text-[var(--text-secondary)]">9-state ladder arbitration</p>
              </div>

              {/* L0 */}
              <div className="p-2.5 rounded-xl border bg-[var(--bg-surface)] space-y-1" style={{ borderColor: 'var(--border-color)' }}>
                <div className="flex items-center justify-between">
                  <span className="text-[10px] font-mono font-bold text-[var(--brand-accent)]">L0: OBSERVABILITY</span>
                  <span className="text-[10px] font-bold px-1.5 py-0.2 rounded text-[var(--success)] bg-[var(--success-bg)]">
                    LOGGED
                  </span>
                </div>
                <p className="text-[11px] text-[var(--text-secondary)]">Immutable audit ledger recording</p>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};
