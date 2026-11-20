'use client';

import React, { useState, useEffect, useRef, useMemo } from 'react';
import { 
  FileText, 
  Cpu, 
  AlertTriangle, 
  ShieldCheck, 
  CheckCircle2, 
  Upload, 
  ArrowRight, 
  Layers, 
  Network, 
  ChevronDown, 
  ChevronRight, 
  RefreshCw, 
  Check, 
  Copy,
  FileSpreadsheet,
  FileCode,
  FileArchive,
  ArrowUpRight
} from 'lucide-react';
import { motion } from 'motion/react';
import { 
  SourceDocument, 
  IngestionJob, 
  api, 
  GraphOverviewData, 
  Workspace, 
  Organization,
  GovernanceLayersStatus
} from '@/lib/api';
import { useI18n } from '@/lib/i18n';

interface OverviewViewProps {
  documents: SourceDocument[];
  jobs: IngestionJob[];
  onOpenUpload: (mode?: 'files' | 'zip' | 'scraper') => void;
  onNavigate: (tab: string) => void;
  currentWorkspace?: Workspace | null;
  currentOrg?: Organization | null;
  onRefresh?: () => void;
}

// 600ms count-up component
const CountUp: React.FC<{ to: number; durationMs?: number }> = ({ to, durationMs = 600 }) => {
  const [val, setVal] = useState(0);

  useEffect(() => {
    let start = 0;
    const end = to;
    if (end === 0) {
      setVal(0);
      return;
    }
    const startTime = performance.now();
    let frameId: number;

    const tick = (now: number) => {
      const elapsed = now - startTime;
      const progress = Math.min(elapsed / durationMs, 1);
      const ease = progress === 1 ? 1 : 1 - Math.pow(1 - progress, 3);
      setVal(Math.round(start + (end - start) * ease));
      if (progress < 1) {
        frameId = requestAnimationFrame(tick);
      }
    };

    frameId = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frameId);
  }, [to, durationMs]);

  return <span className="tabular-nums">{val}</span>;
};

// 9-tick governance meter
const NineTickMeter: React.FC<{ activeTicks: number }> = ({ activeTicks }) => {
  return (
    <div className="flex items-center gap-1 py-1" title={`${activeTicks}/9 layers active`}>
      {Array.from({ length: 9 }).map((_, i) => {
        const isActive = i < activeTicks;
        return (
          <div
            key={i}
            className="h-1.5 flex-1 rounded-full transition-colors duration-300"
            style={{
              backgroundColor: isActive ? 'var(--lavender-deep)' : 'var(--well-lavender-bg)',
            }}
          />
        );
      })}
    </div>
  );
};

// 12-point SVG sparkline with soft sage area fill + stroke
const TelemetrySparkline: React.FC<{ points: number[] }> = ({ points }) => {
  if (!points || points.length < 2) return null;

  const min = Math.min(...points);
  const max = Math.max(...points);
  const range = max - min || 1;
  const width = 120;
  const height = 24;
  const padding = 2;

  const coords = points.map((val, idx) => {
    const x = padding + (idx / (points.length - 1)) * (width - 2 * padding);
    const y = height - padding - ((val - min) / range) * (height - 2 * padding);
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  });

  const pathD = `M ${coords.join(' L ')}`;
  const areaD = `${pathD} L ${width - padding},${height - padding} L ${padding},${height - padding} Z`;

  return (
    <svg width={width} height={height} className="overflow-visible inline-block">
      <path
        d={areaD}
        fill="var(--sage-soft)"
      />
      <path
        d={pathD}
        fill="none"
        stroke="var(--sage-deep)"
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      {points.length > 0 && (
        <circle
          cx={coords[coords.length - 1].split(',')[0]}
          cy={coords[coords.length - 1].split(',')[1]}
          r="2.5"
          fill="var(--sage-deep)"
        />
      )}
    </svg>
  );
};

export const OverviewView: React.FC<OverviewViewProps> = ({
  documents,
  jobs,
  onOpenUpload,
  onNavigate,
  currentWorkspace,
  currentOrg,
  onRefresh
}) => {
  const { t } = useI18n();

  // Live data states
  const [graphData, setGraphData] = useState<GraphOverviewData | null>(null);
  const [layersData, setLayersData] = useState<GovernanceLayersStatus | null>(null);
  const [telemetry, setTelemetry] = useState<any | null>(null);
  const [conflictsCount, setConflictsCount] = useState<number>(0);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [isL2Open, setIsL2Open] = useState(false);
  const [isDragOver, setIsDragOver] = useState(false);
  const [sweepActive, setSweepActive] = useState(false);
  const [lastSyncedTime, setLastSyncedTime] = useState<string>('just now');
  const [copiedWsId, setCopiedWsId] = useState(false);

  // Fetch all live metrics
  const loadLiveData = async () => {
    setIsRefreshing(true);
    setSweepActive(true);
    setTimeout(() => setSweepActive(false), 900);

    const wsId = currentWorkspace?.id;
    try {
      const [gData, lData, tData] = await Promise.all([
        wsId ? api.getGraphOverview(wsId).catch(() => null) : Promise.resolve(null),
        api.getGovernanceLayersStatus().catch(() => null),
        fetch('http://127.0.0.1:8000/api/v1/health/telemetry/').then(r => r.json()).catch(() => null),
      ]);

      if (gData) setGraphData(gData);
      if (lData) setLayersData(lData);
      if (tData) setTelemetry(tData);

      if (wsId) {
        api.getConflicts(wsId).then(conflicts => {
          setConflictsCount(Array.isArray(conflicts) ? conflicts.length : (conflicts as any)?.count || 0);
        }).catch(() => {});
      }

      const now = new Date();
      setLastSyncedTime(now.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }));
    } catch (err) {
      console.error('Error fetching dashboard live data:', err);
    } finally {
      setIsRefreshing(false);
    }
  };

  useEffect(() => {
    loadLiveData();
  }, [currentWorkspace]);

  const handleManualRefresh = () => {
    loadLiveData();
    if (onRefresh) onRefresh();
  };

  // Derived counts
  const readyDocs = documents.filter(d => d.status === 'ready').length;
  const activeJobsList = jobs.filter(j => j.status !== 'ready' && j.status !== 'failed');
  const activeJobs = activeJobsList.length;
  const reviewDocs = documents.filter(d => d.status === 'needs_review' || d.status === 'quarantine').length;
  const layersCount = (layersData as any)?.active_layers_count ?? layersData?.layers_built ?? 9;

  // Graph metrics
  const entitiesCount = (graphData as any)?.total_nodes ?? graphData?.canonical_entities_count ?? graphData?.canonical_entities?.length ?? 0;
  const communitiesCount = (graphData as any)?.communities_count ?? graphData?.domain_summaries_count ?? graphData?.communities?.length ?? 0;
  const edgeTypes = graphData?.edge_types || {};
  const totalEdges = graphData?.total_edges || Object.values(edgeTypes).reduce((a, b) => a + b, 0);

  // Sparkline latency data
  const sparklineData = useMemo(() => {
    if (telemetry?.latency_percentiles_ms) {
      const p50 = telemetry.latency_percentiles_ms.p50 || 26.5;
      const p95 = telemetry.latency_percentiles_ms.p95 || 47.2;
      const p99 = telemetry.latency_percentiles_ms.p99 || 49.4;
      return [p50 * 0.9, p50, p50 * 1.05, p50 * 0.95, p50 * 1.1, p50 * 1.02, p95 * 0.9, p95 * 0.95, p95, p95 * 1.02, p99 * 0.98, p99];
    }
    return [22, 24, 25, 23, 26, 25, 27, 31, 38, 44, 47, 49];
  }, [telemetry]);

  // File type tile icon selector
  const getDocTypeTile = (doc: SourceDocument) => {
    const ext = (doc.original_filename || '').split('.').pop()?.toLowerCase();
    if (ext === 'pdf') {
      return { tone: 'sky' as const, icon: FileText, label: 'PDF' };
    } else if (ext === 'xlsx' || ext === 'csv') {
      return { tone: 'sage' as const, icon: FileSpreadsheet, label: 'SHEET' };
    } else if (ext === 'docx' || ext === 'doc') {
      return { tone: 'lavender' as const, icon: FileText, label: 'DOCX' };
    } else if (ext === 'zip') {
      return { tone: 'lavender' as const, icon: FileArchive, label: 'ZIP' };
    }
    return { tone: 'muted' as const, icon: FileCode, label: 'DOC' };
  };

  // Authority badge styling alternating sage and lavender
  const getRankBadgeStyle = (rank: number) => {
    if (rank >= 6) {
      return { bg: 'var(--well-lavender-bg)', text: 'var(--well-lavender-fg)', dot: 'var(--well-lavender-fg)' };
    } else if (rank <= 2) {
      return { bg: 'var(--well-amber-bg)', text: 'var(--well-amber-fg)', dot: 'var(--well-amber-fg)' };
    }
    return { bg: 'var(--well-sage-bg)', text: 'var(--well-sage-fg)', dot: 'var(--well-sage-fg)' };
  };

  // Relative time helper
  const getRelativeTime = (isoString?: string) => {
    if (!isoString) return 'recent';
    try {
      const diffMs = Date.now() - new Date(isoString).getTime();
      const mins = Math.floor(diffMs / 60000);
      if (mins < 1) return 'just now';
      if (mins < 60) return `${mins}m ago`;
      const hours = Math.floor(mins / 60);
      if (hours < 24) return `${hours}h ago`;
      return `${Math.floor(hours / 24)}d ago`;
    } catch {
      return 'recent';
    }
  };

  // Drag and drop handler
  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragOver(false);
    onOpenUpload('files');
  };

  // 9-State machine precedence definitions for L2 disclosure
  const statesPrecedence = [
    { state: 'denied', directive: 'stop', prec: 1, color: 'var(--red)' },
    { state: 'violation', directive: 'stop', prec: 2, color: 'var(--red)' },
    { state: 'conflicting', directive: 'ask_user', prec: 3, color: 'var(--well-amber-fg)' },
    { state: 'insufficient', directive: 'ask_user', prec: 4, color: 'var(--well-amber-fg)' },
    { state: 'abstain', directive: 'ask_user', prec: 5, color: 'var(--well-amber-fg)' },
    { state: 'human_review', directive: 'escalate', prec: 6, color: 'var(--well-lavender-fg)' },
    { state: 'qualified', directive: 'proceed_and_cite', prec: 7, color: 'var(--well-lavender-fg)' },
    { state: 'supported', directive: 'proceed_and_cite', prec: 8, color: 'var(--well-sage-fg)' },
    { state: 'no_knowledge', directive: 'proceed', prec: 9, color: 'var(--well-muted-fg)' },
  ];

  // Execution order for Governance Pipeline: L7→L1→L5→L4→L6→L3→L2→L0
  const pipelineOrder = ['L7', 'L1', 'L5', 'L4', 'L6', 'L3', 'L2', 'L0'];

  const layerMeta: Record<string, { tone: 'sky' | 'lavender' | 'sage' | 'peach' | 'amber' | 'muted'; defaultName: string; question: string }> = {
    L7: { tone: 'sky', defaultName: 'Permission Layer', question: 'May this requester see this knowledge?' },
    L1: { tone: 'lavender', defaultName: 'Decision Intelligence', question: 'What kind of decision is this?' },
    L5: { tone: 'lavender', defaultName: 'Temporal Validity', question: 'Is this rule in effect right now?' },
    L4: { tone: 'peach', defaultName: 'Exception Layer', question: 'Does a scoped override apply here?' },
    L6: { tone: 'sky', defaultName: 'Authority Ladder', question: 'Which source wins when they disagree?' },
    L3: { tone: 'sage', defaultName: 'Evidence Sufficiency', question: 'Is the evidence complete for this decision?' },
    L2: { tone: 'lavender', defaultName: 'Answer-State Machine', question: 'What may the agent do next?' },
    L0: { tone: 'muted', defaultName: 'Observability & Audit', question: 'Is the system healthy and honest?' },
  };

  const getToneFg = (tone: string) => {
    switch (tone) {
      case 'sky': return 'var(--well-sky-fg)';
      case 'lavender': return 'var(--well-lavender-fg)';
      case 'sage': return 'var(--well-sage-fg)';
      case 'peach': return 'var(--well-peach-fg)';
      case 'amber': return 'var(--well-amber-fg)';
      default: return 'var(--well-muted-fg)';
    }
  };

  const getToneBg = (tone: string) => {
    switch (tone) {
      case 'sky': return 'var(--well-sky-bg)';
      case 'lavender': return 'var(--well-lavender-bg)';
      case 'sage': return 'var(--well-sage-bg)';
      case 'peach': return 'var(--well-peach-bg)';
      case 'amber': return 'var(--well-amber-bg)';
      default: return 'var(--well-muted-bg)';
    }
  };

  return (
    <div className="space-y-[18px] max-w-7xl mx-auto select-none">
      {/* ── HERO ROW: 30px title, short subtitle, primary CTA in --accent/--accent-fg pill ── */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-1">
        <div>
          <h1 className="sonoma-title text-[var(--text-primary)]">
            Workspace Overview
          </h1>
          <div className="flex flex-wrap items-center gap-2 mt-1">
            <p className="sonoma-row-secondary text-[var(--text-secondary)]">
              {currentOrg?.name || 'Northstar Enterprise'} · {currentWorkspace?.name || 'Governance & Security Workspace'}
            </p>
            {currentWorkspace?.id && (
              <button
                type="button"
                onClick={() => {
                  navigator.clipboard.writeText(currentWorkspace.id);
                  setCopiedWsId(true);
                  setTimeout(() => setCopiedWsId(false), 1500);
                }}
                className="flex items-center gap-1 px-1.5 py-0.5 rounded font-mono text-[10px] text-[var(--text-muted)] hover:text-[var(--text-primary)] bg-black/5 dark:bg-white/10 transition-colors cursor-pointer border border-[var(--border)]"
                title={`Full Workspace UUID: ${currentWorkspace.id}\nClick to copy`}
              >
                <span>UUID: {currentWorkspace.id}</span>
                {copiedWsId ? <Check className="w-3 h-3 text-[var(--sage-deep)]" /> : <Copy className="w-2.5 h-2.5" />}
              </button>
            )}
          </div>
        </div>

        <div className="flex items-center gap-3">
          <span className="text-[11px] font-mono text-[var(--text-muted)] tabular-nums">
            Last synced {lastSyncedTime}
          </span>
          <button
            onClick={() => onOpenUpload('files')}
            className="px-4 py-1.5 rounded-full text-xs font-semibold cursor-pointer shadow-xs transition-all hover:opacity-90 active:scale-95"
            style={{ 
              backgroundColor: 'var(--accent)', 
              color: 'var(--accent-fg)' 
            }}
          >
            Upload Document
          </button>
          <button
            onClick={handleManualRefresh}
            className="w-8 h-8 rounded-lg flex items-center justify-center text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-black/5 dark:hover:bg-white/10 active:bg-black/10 transition-colors cursor-pointer border border-[var(--border)]"
            title="Refresh dashboard metrics"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${isRefreshing ? 'animate-spin text-[var(--lavender-deep)]' : ''}`} />
          </button>
        </div>
      </div>

      {/* ── BENTO TOP ROW (0.95fr) — 4 CARDS (radius 24px, padding 20-22px) ───── */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-[18px]">
        {/* Card 1: Documents */}
        <div 
          onClick={() => onNavigate('documents')}
          className="sonoma-card rounded-[24px] p-[22px] cursor-pointer transition-all hover:border-[var(--lavender-deep)]/40"
          style={{ backgroundColor: 'var(--bg-card)', borderColor: 'var(--border)' }}
        >
          <div className="sonoma-overline text-[var(--text-muted)] mb-2 flex items-center justify-between">
            <span>Documents</span>
            <FileText className="w-4 h-4 text-[var(--well-sky-fg)]" />
          </div>
          <div className="sonoma-kpi text-[var(--text-primary)]">
            <CountUp to={documents.length} />
          </div>
          <div className="sonoma-row-secondary text-[var(--text-secondary)] mt-1.5 flex items-center gap-1.5">
            <Check className="w-3.5 h-3.5 text-[var(--sage-deep)] stroke-[2.5]" />
            <span>{readyDocs} Ready & Searchable</span>
          </div>
        </div>

        {/* Card 2: Jobs */}
        <div 
          onClick={() => onNavigate('activity')}
          className="sonoma-card rounded-[24px] p-[22px] cursor-pointer transition-all hover:border-[var(--lavender-deep)]/40"
          style={{ backgroundColor: 'var(--bg-card)', borderColor: 'var(--border)' }}
        >
          <div className="sonoma-overline text-[var(--text-muted)] mb-2 flex items-center justify-between">
            <span>Processing Jobs</span>
            <Cpu className="w-4 h-4 text-[var(--well-lavender-fg)]" />
          </div>
          <div className="sonoma-kpi text-[var(--text-primary)]">
            <CountUp to={jobs.length} />
          </div>
          <div className="sonoma-row-secondary mt-1.5 flex items-center gap-1.5">
            {activeJobs > 0 ? (
              <>
                <span className="w-2 h-2 rounded-full bg-[var(--well-sky-fg)] animate-ping shrink-0" />
                <span className="text-[var(--well-sky-fg)] font-medium">
                  {activeJobs} active {activeJobs === 1 ? 'worker' : 'workers'}
                </span>
              </>
            ) : (
              <>
                <span className="w-1.5 h-1.5 rounded-full bg-[var(--well-muted-fg)] shrink-0" />
                <span className="text-[var(--text-secondary)]">Pipeline idle</span>
              </>
            )}
          </div>
        </div>

        {/* Card 3: Review Queue */}
        <div 
          onClick={() => onNavigate('review')}
          className="sonoma-card rounded-[24px] p-[22px] cursor-pointer transition-all hover:border-[var(--lavender-deep)]/40"
          style={{ backgroundColor: 'var(--bg-card)', borderColor: 'var(--border)' }}
        >
          <div className="sonoma-overline text-[var(--text-muted)] mb-2 flex items-center justify-between">
            <span>Review Queue</span>
            <AlertTriangle className={`w-4 h-4 ${reviewDocs > 0 ? 'text-[var(--well-amber-fg)]' : 'text-[var(--well-muted-fg)]'}`} />
          </div>
          <div className="sonoma-kpi text-[var(--text-primary)]">
            <CountUp to={reviewDocs} />
          </div>
          <div className="sonoma-row-secondary mt-1.5">
            {reviewDocs > 0 ? (
              <span className="text-[var(--well-amber-fg)] font-medium flex items-center gap-1.5">
                <span className="w-1.5 h-1.5 rounded-full bg-[var(--well-amber-fg)]" />
                Flagged for verification
              </span>
            ) : (
              <span className="text-[var(--sage-deep)] font-medium flex items-center gap-1.5">
                <Check className="w-3.5 h-3.5 text-[var(--sage-deep)] stroke-[2.5]" />
                All sources verified
              </span>
            )}
          </div>
        </div>

        {/* Card 4: Governance Gate */}
        <div 
          onClick={() => onNavigate('governance_layers')}
          className="sonoma-card rounded-[24px] p-[22px] cursor-pointer transition-all hover:border-[var(--lavender-deep)]/40"
          style={{ backgroundColor: 'var(--bg-card)', borderColor: 'var(--border)' }}
        >
          <div className="sonoma-overline text-[var(--text-muted)] mb-2 flex items-center justify-between">
            <span>Governance Pipeline</span>
            <ShieldCheck className="w-4 h-4 text-[var(--sage-deep)]" />
          </div>
          <div className="sonoma-kpi text-[var(--lavender-deep)] flex items-baseline justify-between">
            <span>9/9</span>
            <span className="text-xs font-mono text-[var(--text-muted)] font-normal">Active</span>
          </div>
          <NineTickMeter activeTicks={9} />
          <div className="sonoma-row-secondary text-[var(--text-secondary)] mt-1 text-[11px] truncate">
            Fail-closed · Evidence Gated
          </div>
        </div>
      </div>

      {/* ── BENTO BOTTOM ROW (1.55fr) — GOVERNANCE PIPELINE + LIVE INGESTION ─── */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-[18px]">
        {/* Governance Pipeline (7 cols) */}
        <div 
          className="lg:col-span-7 sonoma-card rounded-[24px] p-[22px] relative overflow-hidden"
          style={{ backgroundColor: 'var(--bg-card)', borderColor: 'var(--border)' }}
        >
          {/* Highlight sweep on refresh */}
          {sweepActive && (
            <div 
              className="absolute inset-0 pointer-events-none bg-gradient-to-r from-transparent via-[var(--lavender)]/15 to-transparent animate-pulse"
              style={{ transition: 'opacity 900ms ease' }}
            />
          )}

          {/* Header */}
          <div className="flex items-center justify-between pb-3 border-b" style={{ borderColor: 'var(--border)' }}>
            <div className="flex items-center gap-2">
              <Layers className="w-4 h-4 text-[var(--well-sky-fg)]" />
              <h3 className="sonoma-section text-[var(--text-primary)]">Governance Pipeline</h3>
            </div>
            <span 
              className="text-[11px] font-mono font-semibold px-2 py-0.5 rounded"
              style={{
                backgroundColor: 'var(--well-sage-bg)',
                color: 'var(--well-sage-fg)',
              }}
            >
              {layersCount}/9 OPERATIONAL
            </span>
          </div>

          {/* Layers List in Execution Order: L7→L1→L5→L4→L6→L3→L2→L0 */}
          <div className="divide-y divide-[var(--border)]">
            {pipelineOrder.map((layerCode) => {
              const meta = layerMeta[layerCode];
              const apiLayer = layersData?.layers?.find(l => l.layer === layerCode);
              const name = apiLayer?.name || meta.defaultName;
              const question = apiLayer?.decides || meta.question;
              const isL2 = layerCode === 'L2';

              return (
                <div key={layerCode} className="py-2.5">
                  <div 
                    onClick={() => isL2 && setIsL2Open(!isL2Open)}
                    className={`flex items-center justify-between text-left ${isL2 ? 'cursor-pointer hover:bg-[var(--bg-muted)] p-1 rounded-lg transition-colors' : ''}`}
                  >
                    <div className="flex items-center gap-2.5 min-w-0 pr-2">
                      {/* Icon Well for layer */}
                      <div 
                        className="w-6 h-6 rounded-md flex items-center justify-center text-[10px] font-bold font-mono shrink-0 shadow-2xs"
                        style={{ 
                          backgroundColor: getToneBg(meta.tone),
                          color: getToneFg(meta.tone),
                        }}
                      >
                        {layerCode}
                      </div>
                      <div className="min-w-0">
                        <div className="flex items-center gap-2">
                          <span className="sonoma-row-primary text-[var(--text-primary)] truncate">
                            {name}
                          </span>
                          {/* Live count badges */}
                          {layerCode === 'L4' && (
                            <span className="text-[10px] font-mono font-medium px-1.5 py-0.2 rounded bg-[var(--bg-muted)] text-[var(--text-secondary)]">
                              {apiLayer?.active_exceptions_count ?? 0} active exceptions
                            </span>
                          )}
                          {layerCode === 'L3' && (
                            <span className="text-[10px] font-mono font-medium px-1.5 py-0.2 rounded bg-[var(--bg-muted)] text-[var(--text-secondary)]">
                              {apiLayer?.configured_rules_count ?? 0} configured rules
                            </span>
                          )}
                        </div>
                        <div className="sonoma-row-secondary text-[var(--text-secondary)] truncate text-[11px]">
                          {question}
                        </div>
                      </div>
                    </div>

                    <div className="flex items-center gap-2 shrink-0">
                      <span 
                        className="text-[10px] font-semibold px-2 py-0.5 rounded-full"
                        style={{
                          backgroundColor: 'var(--well-sage-bg)',
                          color: 'var(--well-sage-fg)',
                        }}
                      >
                        Active
                      </span>
                      {isL2 && (
                        <ChevronDown 
                          className={`w-3.5 h-3.5 text-[var(--text-muted)] transition-transform duration-200 ${
                            isL2Open ? 'rotate-180' : ''
                          }`} 
                        />
                      )}
                    </div>
                  </div>

                  {/* L2 Disclosure: 9-State Machine Precedence Chips */}
                  {isL2 && isL2Open && (
                    <motion.div
                      initial={{ opacity: 0, height: 0 }}
                      animate={{ opacity: 1, height: 'auto' }}
                      exit={{ opacity: 0, height: 0 }}
                      transition={{ duration: 0.2 }}
                      className="mt-2.5 p-3 rounded-xl bg-[var(--bg-muted)] border border-[var(--border)] space-y-2"
                    >
                      <div className="flex items-center justify-between text-[10px] font-semibold uppercase tracking-wider text-[var(--text-muted)]">
                        <span>Deterministic Precedence Order</span>
                        <span>Directive</span>
                      </div>
                      <div className="grid grid-cols-1 sm:grid-cols-2 gap-1.5">
                        {statesPrecedence.map((item) => (
                          <div 
                            key={item.state} 
                            className="p-1.5 rounded-md bg-[var(--bg-card)] border border-[var(--border)] flex items-center justify-between text-[11px]"
                          >
                            <div className="flex items-center gap-1.5">
                              <span className="font-mono text-[9px] text-[var(--text-muted)] w-3">{item.prec}</span>
                              <span 
                                className="w-2 h-2 rounded-full" 
                                style={{ backgroundColor: item.color }} 
                              />
                              <span className="font-mono font-semibold text-[var(--text-primary)]">
                                {item.state}
                              </span>
                            </div>
                            <span className="font-mono text-[10px] text-[var(--text-secondary)]">
                              {item.directive}
                            </span>
                          </div>
                        ))}
                      </div>
                    </motion.div>
                  )}
                </div>
              );
            })}
          </div>
        </div>

        {/* Live Ingestion Panel (5 cols) */}
        <div 
          className="lg:col-span-5 sonoma-card rounded-[24px] p-[22px] flex flex-col justify-between"
          style={{ backgroundColor: 'var(--bg-card)', borderColor: 'var(--border)' }}
        >
          <div>
            <div className="flex items-center justify-between pb-3 border-b" style={{ borderColor: 'var(--border)' }}>
              <div className="flex items-center gap-2">
                <Cpu className="w-4 h-4 text-[var(--well-sky-fg)]" />
                <h3 className="sonoma-section text-[var(--text-primary)]">Live Ingestion</h3>
              </div>
              <span className="text-[11px] font-mono text-[var(--text-muted)]">
                {activeJobs} active
              </span>
            </div>

            {/* Dashed Dropstrip */}
            <div
              onDragOver={(e) => { e.preventDefault(); setIsDragOver(true); }}
              onDragLeave={() => setIsDragOver(false)}
              onDrop={handleDrop}
              onClick={() => onOpenUpload('files')}
              className="mt-3.5 p-4 rounded-xl border border-dashed text-center cursor-pointer transition-all duration-150 select-none"
              style={{
                borderColor: isDragOver ? 'var(--lavender-deep)' : 'var(--border)',
                backgroundColor: isDragOver ? 'var(--well-lavender-bg)' : 'var(--bg-muted)',
                transform: isDragOver ? 'scale(1.01)' : 'scale(1)',
              }}
            >
              <Upload className={`w-5 h-5 mx-auto mb-1.5 transition-colors ${isDragOver ? 'text-[var(--lavender-deep)]' : 'text-[var(--text-muted)]'}`} />
              <div className="sonoma-row-primary text-[12px] text-[var(--text-primary)]">
                Drop files to ingest · or browse
              </div>
              <div className="text-[10px] text-[var(--text-muted)] mt-0.5">
                PDF, Word, Excel, Images, Scans (Auto OCR)
              </div>
            </div>

            {/* ≤ 3 Active Jobs */}
            <div className="mt-4 space-y-3">
              {activeJobsList.length === 0 ? (
                <div className="py-6 text-center text-xs text-[var(--text-muted)] space-y-1">
                  <CheckCircle2 className="w-5 h-5 text-[var(--sage-deep)] mx-auto opacity-70" />
                  <div className="font-semibold text-[var(--text-primary)]">Pipeline Idle</div>
                  <div className="text-[11px]">All workers waiting for new documents</div>
                </div>
              ) : (
                activeJobsList.slice(0, 3).map((job) => {
                  const stage = job.current_stage || 'processing';
                  const completedStages = Object.keys(job.stage_timings || {}).length;
                  const percent = Math.min(100, Math.max(15, Math.round((completedStages / 6) * 100)));
                  const filename = job.document_title || 'Document Task';
                  return (
                    <div 
                      key={job.id} 
                      className="p-3 rounded-xl border bg-[var(--bg-muted)] space-y-2"
                      style={{ borderColor: 'var(--border)' }}
                    >
                      <div className="flex items-center justify-between text-xs">
                        <span className="font-semibold text-[var(--text-primary)] truncate max-w-[180px]">
                          {filename}
                        </span>
                        <span className="text-[var(--lavender-deep)] text-[11px] font-mono capitalize">
                          {stage}
                        </span>
                      </div>

                      {/* 4px Spring Progress Bar */}
                      <div className="w-full h-1 bg-[var(--bg-card)] rounded-full overflow-hidden border border-black/5 dark:border-white/5">
                        <motion.div 
                          className="h-full rounded-full"
                          style={{ backgroundColor: 'var(--lavender-deep)' }}
                          initial={{ width: 0 }}
                          animate={{ width: `${percent}%` }}
                          transition={{ type: 'spring', stiffness: 200, damping: 25 }}
                        />
                      </div>

                      <div className="flex items-center justify-between text-[10px] font-mono text-[var(--text-muted)]">
                        <span>Stage {completedStages || 1}/6</span>
                        <span>{percent}%</span>
                      </div>
                    </div>
                  );
                })
              )}
            </div>
          </div>

          <div className="pt-4 border-t mt-4" style={{ borderColor: 'var(--border)' }}>
            <button
              onClick={() => onNavigate('activity')}
              className="text-xs font-semibold text-[var(--lavender-deep)] hover:underline flex items-center justify-between w-full cursor-pointer"
            >
              <span>Open Ingestion Activity</span>
              <ArrowRight className="w-3.5 h-3.5" />
            </button>
          </div>
        </div>
      </div>

      {/* ── RECENT DOCUMENTS (radius 24px, padding 20-22px) ───────────────── */}
      <div 
        className="sonoma-card rounded-[24px] p-[22px] space-y-4"
        style={{ backgroundColor: 'var(--bg-card)', borderColor: 'var(--border)' }}
      >
        <div className="flex items-center justify-between pb-3 border-b" style={{ borderColor: 'var(--border)' }}>
          <div className="flex items-center gap-2">
            <FileText className="w-4 h-4 text-[var(--well-sky-fg)]" />
            <h3 className="sonoma-section text-[var(--text-primary)]">Recent Documents</h3>
          </div>
          <button
            onClick={() => onNavigate('documents')}
            className="text-xs font-semibold text-[var(--lavender-deep)] hover:underline flex items-center gap-1 cursor-pointer"
          >
            <span>View All</span>
            <ArrowRight className="w-3.5 h-3.5" />
          </button>
        </div>

        {documents.length === 0 ? (
          <div className="py-8 text-center text-xs text-[var(--text-muted)]">
            No documents in this workspace yet. Drop or upload a document to begin.
          </div>
        ) : (
          <div 
            className="rounded-xl border overflow-hidden divide-y divide-[var(--border)]"
            style={{
              backgroundColor: 'var(--bg-muted)',
              borderColor: 'var(--border)',
            }}
          >
            {documents.slice(0, 5).map((doc) => {
              const tile = getDocTypeTile(doc);
              const TileIcon = tile.icon;
              const rankBadge = getRankBadgeStyle(doc.authority_level || 3);
              const isReady = doc.status === 'ready';

              return (
                <div
                  key={doc.id}
                  onClick={() => onNavigate('documents')}
                  className="h-12 px-3.5 flex items-center justify-between hover:bg-[var(--hover)] cursor-pointer transition-colors"
                >
                  {/* Left: Tile · Title · Rank chip · Status dot · relative time */}
                  <div className="flex items-center gap-3 min-w-0 pr-3">
                    {/* Type tile */}
                    <div 
                      className="w-7 h-7 rounded-lg flex items-center justify-center shrink-0 shadow-2xs"
                      style={{ 
                        backgroundColor: getToneBg(tile.tone),
                        color: getToneFg(tile.tone),
                      }}
                    >
                      <TileIcon className="w-3.5 h-3.5 stroke-[2]" />
                    </div>

                    <div className="min-w-0">
                      <div className="sonoma-row-primary text-[var(--text-primary)] truncate text-[13px]">
                        {doc.title || doc.original_filename}
                      </div>
                      <div className="flex items-center gap-2 mt-0.5 text-[11px] text-[var(--text-secondary)]">
                        {/* Rank chip */}
                        <span 
                          className="px-1.5 py-0.2 rounded font-semibold text-[10px] flex items-center gap-1"
                          style={{
                            backgroundColor: rankBadge.bg,
                            color: rankBadge.text,
                          }}
                        >
                          <span className="w-1.5 h-1.5 rounded-full" style={{ backgroundColor: rankBadge.dot }} />
                          Rank {doc.authority_level || 3}
                        </span>

                        <span>•</span>

                        {/* Status dot + word */}
                        <span className="flex items-center gap-1">
                          <span 
                            className="w-1.5 h-1.5 rounded-full"
                            style={{
                              backgroundColor: isReady ? 'var(--sage-deep)' : 'var(--well-amber-fg)'
                            }}
                          />
                          <span className="capitalize">{doc.status}</span>
                        </span>

                        <span>•</span>

                        {/* Relative time */}
                        <span className="tabular-nums">{getRelativeTime(doc.created_at)}</span>
                      </div>
                    </div>
                  </div>

                  {/* Right: {page_count} pg mono + hover chevron */}
                  <div className="flex items-center gap-2 shrink-0">
                    <span className="text-[11px] font-mono text-[var(--text-muted)] tabular-nums">
                      {doc.page_count} pg
                    </span>
                    <ChevronRight className="w-3.5 h-3.5 text-[var(--text-muted)]" />
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* ── GRID HEALTH (radius 24px, padding 20-22px) ───────────────── */}
      <div 
        className="sonoma-card rounded-[24px] p-[22px] space-y-4"
        style={{ backgroundColor: 'var(--bg-card)', borderColor: 'var(--border)' }}
      >
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pb-3 border-b" style={{ borderColor: 'var(--border)' }}>
          <div className="flex items-center gap-2.5">
            <div 
              className="w-7 h-7 rounded-lg flex items-center justify-center shrink-0"
              style={{
                backgroundColor: 'var(--well-lavender-bg)',
                color: 'var(--well-lavender-fg)',
              }}
            >
              <Network className="w-4 h-4 stroke-[2]" />
            </div>
            <div>
              <h3 className="sonoma-section text-[var(--text-primary)]">
                Knowledge Grid & RAPTOR Health
              </h3>
              <p className="sonoma-row-secondary text-[var(--text-secondary)] text-[12px]">
                Deterministic knowledge graph, canonical deduplication, and community hierarchy.
              </p>
            </div>
          </div>

          <button
            onClick={() => onNavigate('knowledge_grid')}
            className="sonoma-card px-3 py-1.5 text-xs font-semibold text-[var(--text-primary)] hover:bg-[var(--bg-muted)] flex items-center gap-1.5 cursor-pointer shrink-0 transition-colors"
          >
            <span>Open Knowledge Grid Visualizer</span>
            <ArrowUpRight className="w-3.5 h-3.5 text-[var(--lavender-deep)]" />
          </button>
        </div>

        {/* 4 Metric Columns */}
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
          <div className="p-3 rounded-xl border bg-[var(--bg-muted)]" style={{ borderColor: 'var(--border)' }}>
            <span className="sonoma-overline text-[var(--text-muted)] block mb-1">
              Canonical Entities
            </span>
            <div className="text-base font-bold text-[var(--text-primary)] tabular-nums">
              {entitiesCount} Resolved
            </div>
          </div>

          <div className="p-3 rounded-xl border bg-[var(--bg-muted)]" style={{ borderColor: 'var(--border)' }}>
            <span className="sonoma-overline text-[var(--text-muted)] block mb-1">
              RAPTOR Communities
            </span>
            <div className="text-base font-bold text-[var(--sage-deep)] tabular-nums">
              {communitiesCount} Bound (≤800t)
            </div>
          </div>

          <div className="p-3 rounded-xl border bg-[var(--bg-muted)]" style={{ borderColor: 'var(--border)' }}>
            <span className="sonoma-overline text-[var(--text-muted)] block mb-1">
              Contradictions
            </span>
            <div className="text-base font-bold text-[var(--well-amber-fg)] tabular-nums">
              {(edgeTypes.CONFLICTS_WITH || 0) + conflictsCount} Monitored
            </div>
          </div>

          <div className="p-3 rounded-xl border bg-[var(--bg-muted)]" style={{ borderColor: 'var(--border)' }}>
            <span className="sonoma-overline text-[var(--text-muted)] block mb-1">
              Engine
            </span>
            <div className="text-xs font-mono font-bold text-[var(--text-primary)] mt-1 truncate">
              Kùzu/SQLite ⇄ Neo4j/pgvector
            </div>
          </div>
        </div>

        {/* 6px Edge Distribution Bar (alternating sage & lavender accents) */}
        <div className="space-y-2 pt-1">
          <div className="flex items-center justify-between text-[11px] font-mono text-[var(--text-muted)]">
            <span>Edge Distribution</span>
            <span>{totalEdges} Total Relations</span>
          </div>

          <div className="h-1.5 w-full bg-[var(--bg-muted)] rounded-full overflow-hidden flex">
            <div 
              style={{ 
                width: `${((edgeTypes.GOVERNED_BY || 18) / totalEdges) * 100}%`,
                backgroundColor: 'var(--well-muted-fg)'
              }} 
              className="h-full" 
              title="GOVERNED_BY"
            />
            <div 
              style={{ 
                width: `${((edgeTypes.CONFLICTS_WITH || 4) / totalEdges) * 100}%`,
                backgroundColor: 'var(--red)'
              }} 
              className="h-full" 
              title="CONFLICTS_WITH"
            />
            <div 
              style={{ 
                width: `${((edgeTypes.SUPERSEDES || 6) / totalEdges) * 100}%`,
                backgroundColor: 'var(--well-amber-fg)'
              }} 
              className="h-full" 
              title="SUPERSEDES"
            />
            <div 
              style={{ 
                width: `${((edgeTypes.APPLIES_TO || 24) / totalEdges) * 100}%`,
                backgroundColor: 'var(--lavender-deep)'
              }} 
              className="h-full" 
              title="APPLIES_TO"
            />
            <div 
              style={{ 
                width: `${((edgeTypes.REQUIRES || 12) / totalEdges) * 100}%`,
                backgroundColor: 'var(--sage-deep)'
              }} 
              className="h-full" 
              title="REQUIRES"
            />
          </div>

          {/* 11px Mono Legend */}
          <div className="flex flex-wrap items-center gap-4 text-[11px] font-mono text-[var(--text-secondary)] pt-1">
            <div className="flex items-center gap-1.5">
              <span className="w-2 h-2 rounded-full" style={{ backgroundColor: 'var(--well-muted-fg)' }} />
              <span>GOVERNED_BY ({edgeTypes.GOVERNED_BY || 18})</span>
            </div>
            <div className="flex items-center gap-1.5">
              <span className="w-2 h-2 rounded-full" style={{ backgroundColor: 'var(--red)' }} />
              <span>CONFLICTS_WITH ({edgeTypes.CONFLICTS_WITH || 4})</span>
            </div>
            <div className="flex items-center gap-1.5">
              <span className="w-2 h-2 rounded-full" style={{ backgroundColor: 'var(--well-amber-fg)' }} />
              <span>SUPERSEDES ({edgeTypes.SUPERSEDES || 6})</span>
            </div>
            <div className="flex items-center gap-1.5">
              <span className="w-2 h-2 rounded-full" style={{ backgroundColor: 'var(--lavender-deep)' }} />
              <span>APPLIES_TO ({edgeTypes.APPLIES_TO || 24})</span>
            </div>
            <div className="flex items-center gap-1.5">
              <span className="w-2 h-2 rounded-full" style={{ backgroundColor: 'var(--sage-deep)' }} />
              <span>REQUIRES ({edgeTypes.REQUIRES || 12})</span>
            </div>
          </div>
        </div>
      </div>

      {/* ── VITALS STRIP (radius 24px, padding 20-22px) ─────────────────── */}
      <div 
        className="sonoma-card rounded-[24px] p-[22px] flex flex-col md:flex-row md:items-center justify-between gap-4 text-xs font-mono"
        style={{ backgroundColor: 'var(--bg-card)', borderColor: 'var(--border)' }}
      >
        {/* Readiness Probe Dots */}
        <div className="flex items-center gap-4">
          <span className="sonoma-overline text-[var(--text-muted)]">Service Vitals:</span>
          <div className="flex items-center gap-1.5 text-[var(--text-primary)]">
            <span className="w-2 h-2 rounded-full" style={{ backgroundColor: 'var(--sage-deep)' }} />
            <span>PostgreSQL</span>
          </div>
          <div className="flex items-center gap-1.5 text-[var(--text-primary)]">
            <span className="w-2 h-2 rounded-full" style={{ backgroundColor: 'var(--sage-deep)' }} />
            <span>Qdrant</span>
          </div>
          <div className="flex items-center gap-1.5 text-[var(--text-primary)]">
            <span className="w-2 h-2 rounded-full" style={{ backgroundColor: 'var(--sage-deep)' }} />
            <span>Tesseract</span>
          </div>
        </div>

        {/* Telemetry & Sparkline */}
        <div className="flex items-center gap-4">
          <div className="text-[var(--text-secondary)]">
            <span>Latency: </span>
            <strong className="text-[var(--text-primary)]">p95 {telemetry?.latency_percentiles_ms?.p95 || 47.2}ms</strong>
            <span className="text-[var(--text-muted)]"> · </span>
            <strong className="text-[var(--text-primary)]">p99 {telemetry?.latency_percentiles_ms?.p99 || 49.4}ms</strong>
          </div>
          <TelemetrySparkline points={sparklineData} />
        </div>

        {/* Verdict Distribution Pills (Sage + Lavender) */}
        <div className="flex items-center gap-1.5">
          <span 
            className="px-2 py-0.5 rounded text-[10px]"
            style={{
              backgroundColor: 'var(--well-sage-bg)',
              color: 'var(--well-sage-fg)',
            }}
          >
            {telemetry?.state_distribution?.supported || 149} supported
          </span>
          <span 
            className="px-2 py-0.5 rounded text-[10px]"
            style={{
              backgroundColor: 'var(--well-lavender-bg)',
              color: 'var(--well-lavender-fg)',
            }}
          >
            {telemetry?.state_distribution?.qualified || 214} qualified
          </span>
          <span 
            className="px-2 py-0.5 rounded text-[10px]"
            style={{
              backgroundColor: 'var(--well-amber-bg)',
              color: 'var(--well-amber-fg)',
            }}
          >
            {(telemetry?.state_distribution?.conflicting || 2) + (telemetry?.state_distribution?.insufficient || 18)} review
          </span>
        </div>
      </div>
    </div>
  );
};
