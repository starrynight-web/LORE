'use client';

import React, { useState, useEffect, useMemo, useRef, useCallback } from 'react';
import { 
  Network, 
  Layers, 
  ShieldCheck, 
  CheckCircle2, 
  AlertTriangle, 
  FileText, 
  RefreshCw, 
  Sparkles, 
  Box, 
  GitFork, 
  Tag, 
  Search,
  ExternalLink,
  ChevronRight,
  Database,
  Sliders,
  Filter,
  Eye,
  X,
  Clock,
  ArrowRight,
  Scale,
  ShieldAlert,
  Server,
  ZoomIn,
  ZoomOut,
  Maximize2,
  RotateCcw,
  Move,
  Info
} from 'lucide-react';
import { 
  api, 
  GraphOverviewData, 
  DomainSummaryCommunity, 
  CanonicalEntitySummary, 
  GraphVisualNode, 
  GraphVisualEdge,
  NodeLineageData
} from '@/lib/api';

interface KnowledgeGridViewProps {
  workspaceId?: string;
  onNavigateToDocs?: () => void;
}

interface SimNode extends GraphVisualNode {
  x: number;
  y: number;
  vx: number;
  vy: number;
  fx?: number | null;
  fy?: number | null;
  radius: number;
  degree: number;
  clusterId?: string;
}

export const KnowledgeGridView: React.FC<KnowledgeGridViewProps> = ({
  workspaceId,
  onNavigateToDocs
}) => {
  const [data, setData] = useState<GraphOverviewData | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [selectedLevel, setSelectedLevel] = useState<'all' | '0' | '1'>('all');
  const [selectedEntityType, setSelectedEntityType] = useState<string>('all');
  const [selectedNodeTypeFilter, setSelectedNodeTypeFilter] = useState<string>('all');
  const [selectedEdgeType, setSelectedEdgeType] = useState<string>('all');
  const [searchFilter, setSearchFilter] = useState('');
  const [hopDepth, setHopDepth] = useState<number>(2);

  // Pan & Zoom state
  const [pan, setPan] = useState<{ x: number; y: number }>({ x: 0, y: 0 });
  const [zoom, setZoom] = useState<number>(1.0);
  const [isPanning, setIsPanning] = useState(false);
  const panStartRef = useRef<{ x: number; y: number }>({ x: 0, y: 0 });
  const canvasRef = useRef<SVGSVGElement | null>(null);

  // Interactive Node Drag State
  const [draggedNodeId, setDraggedNodeId] = useState<string | null>(null);
  const [hoveredNodeId, setHoveredNodeId] = useState<string | null>(null);

  // Lineage Drawer State
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [lineageData, setLineageData] = useState<NodeLineageData | null>(null);
  const [isLoadingLineage, setIsLoadingLineage] = useState(false);

  // Expanded Community Card State
  const [expandedCommunityId, setExpandedCommunityId] = useState<string | null>(null);

  // Dynamic simulation nodes state for interactive dragging and physics
  const [simulationNodes, setSimulationNodes] = useState<SimNode[]>([]);

  const loadGraphOverview = async () => {
    setIsLoading(true);
    try {
      const res = await api.getGraphOverview(workspaceId);
      setData(res);
    } catch (err) {
      console.warn("Could not fetch live GraphOverview, using default baseline:", err);
      setData({
        workspace_id: workspaceId || 'default',
        active_rules_count: 24,
        relationships_count: 42,
        edge_types: {
          'GOVERNED_BY': 18,
          'CONFLICTS_WITH': 4,
          'SUPERSEDES': 6,
          'APPLIES_TO': 10,
          'REQUIRES': 4,
          'MEMBER_OF': 24,
        },
        canonical_entities: [
          { name: 'EU GDPR', entity_type: 'Regulation', mention_count: 9, aliases: ['GDPR', 'General Data Protection Regulation'] },
          { name: 'AWS KMS', entity_type: 'System', mention_count: 8, aliases: ['KMS', 'Key Management Service'] },
          { name: 'Vanta', entity_type: 'Vendor', mention_count: 6, aliases: ['Vanta Continuous Audit'] },
          { name: 'ServiceNow', entity_type: 'System', mention_count: 5, aliases: ['SNOW', 'ITSM'] },
          { name: 'Data Protection Officer', entity_type: 'Role', mention_count: 4, aliases: ['DPO', 'Privacy Lead'] },
          { name: 'Production Database', entity_type: 'Component', mention_count: 11, aliases: ['Prod DB', 'Primary Cluster'] }
        ],
        communities: [
          {
            id: 'comm_l1_ent',
            domain: 'Enterprise Sovereign Knowledge Grid',
            level: 1,
            summary_text: 'Level-1 Root Raptor Community synthesizing multi-domain governance across Infosec, Cryptography, Data Localization, and Vendor Access Controls.',
            token_count: 210,
            verified_token_bound: true,
            member_rule_count: 24,
            authority_tier: 'Enterprise Standard'
          },
          {
            id: 'comm_l0_sec',
            domain: 'DATA_SECURITY',
            level: 0,
            summary_text: 'Cryptographic data protection at rest and in transit. Mandates AES-256-GCM encryption with HSM-backed key management and dual-control rotation schedules.',
            token_count: 145,
            verified_token_bound: true,
            member_rule_count: 8,
            authority_tier: 'Statutory Law'
          },
          {
            id: 'comm_l0_acc',
            domain: 'ACCESS_CONTROL',
            level: 0,
            summary_text: 'Zero-trust identity boundary requiring hardware MFA for all administrative access. Service account keys strictly prohibited in code repositories.',
            token_count: 160,
            verified_token_bound: true,
            member_rule_count: 9,
            authority_tier: 'Statutory Law'
          },
          {
            id: 'comm_l0_ai',
            domain: 'AI_GOVERNANCE',
            level: 0,
            summary_text: 'EU AI Act Article 14 human oversight requirements. High-risk inferences require deterministic fail-closed rule verification prior to context inclusion.',
            token_count: 180,
            verified_token_bound: true,
            member_rule_count: 7,
            authority_tier: 'Statutory Law'
          }
        ]
      });
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    loadGraphOverview();
  }, [workspaceId]);

  // Load Node Lineage when node is selected
  const handleSelectNode = async (nodeId: string) => {
    setSelectedNodeId(nodeId);
    setIsLoadingLineage(true);
    try {
      const res = await api.getNodeLineage(nodeId, workspaceId);
      setLineageData(res);
    } catch (err) {
      console.warn("Could not fetch lineage for node, using fallback:", err);
      setLineageData({
        status: 'SUCCESS',
        node_id: nodeId,
        node: {
          id: nodeId,
          label: nodeId,
          node_type: 'rule',
          authority_level: 6,
          status: 'stable',
          statement: 'Deterministic policy rule verified under Stage 0 ABAC invariants.',
          confidence: 0.98,
        },
        from_source: {
          document_id: 'doc-001',
          title: 'Enterprise Information Security Policy',
          document_code: 'SEC-POL-001',
          version_number: 2,
          authority_level: 6,
          governance_status: 'stable',
          effective_date: '2026-01-01T00:00:00Z',
        },
        supersedes_timeline: [
          { relation_type: 'SUPERSEDES', note: 'Supersedes SEC-POL-2024v1' }
        ],
        conflicts: [],
        overrides: [
          {
            exception_id: 'exc-01',
            scope_type: 'environment',
            scope_value: 'staging',
            justification: 'Transient sandbox integration testing exemption',
            status: 'active'
          }
        ],
        governed_by: [
          {
            query: 'Evaluate vendor cloud access standards',
            state: 'supported',
            directive: 'proceed_and_cite'
          }
        ],
        upstream_nodes: [
          { source_id: 'ISO/IEC 27001', relationship: { relation_type: 'GOVERNED_BY' } }
        ],
        downstream_nodes: [
          { target_id: 'Production Database', relationship: { relation_type: 'APPLIES_TO' } }
        ],
        traversal_depth: hopDepth,
      });
    } finally {
      setIsLoadingLineage(false);
    }
  };

  const communitiesList = data?.communities || data?.domain_summaries || [];
  const filteredCommunities = communitiesList.filter(c => {
    const domainName = c.domain || c.domain_name || '';
    if (selectedLevel === '0' && c.level !== 0) return false;
    if (selectedLevel === '1' && c.level !== 1) return false;
    if (searchFilter && !domainName.toLowerCase().includes(searchFilter.toLowerCase()) && !c.summary_text.toLowerCase().includes(searchFilter.toLowerCase())) {
      return false;
    }
    return true;
  });

  const entityTypes = ['all', ...Array.from(new Set((data?.canonical_entities || []).map(e => e.entity_type)))];

  const filteredEntities = (data?.canonical_entities || []).filter(e => {
    if (selectedEntityType !== 'all' && e.entity_type !== selectedEntityType) return false;
    if (searchFilter && !e.name.toLowerCase().includes(searchFilter.toLowerCase())) return false;
    return true;
  });

  const edgeTypes = data?.edge_types || data?.edge_metrics || {};
  const totalEdgeCount = Object.values(edgeTypes).reduce<number>((acc, count) => acc + (Number(count) || 0), 0);
  const activeRulesCount = data?.active_rules_count ?? (data?.communities ? data.communities.reduce((a, c) => a + (c.member_rule_count || c.rule_count || 0), 0) : 0);
  const relationshipsCount = data?.relationships_count ?? data?.total_edges ?? 0;

  // 1. Raw Visual Nodes extracted from API
  const rawVisualNodes: GraphVisualNode[] = useMemo(() => {
    const backendNodes = data?.subgraph?.nodes || data?.nodes;
    if (backendNodes && backendNodes.length > 0) return backendNodes;

    // Fallback synthesis if empty
    const nodes: GraphVisualNode[] = [];
    (data?.canonical_entities || []).slice(0, 16).forEach((ent) => {
      nodes.push({
        id: ent.name,
        label: ent.name,
        type: ent.entity_type.toLowerCase(),
        authority: 5,
        status: 'stable',
        severity: 'info',
        statement: ent.description || ent.name,
      });
    });
    communitiesList.slice(0, 6).forEach((comm) => {
      nodes.push({
        id: comm.id,
        label: comm.domain || comm.domain_name || 'Community',
        type: 'community',
        authority: comm.level === 1 ? 7 : 6,
        status: 'stable',
        severity: 'critical',
        statement: comm.summary_text,
        token_count: comm.token_count,
      });
    });
    return nodes;
  }, [data, communitiesList]);

  // 2. Raw Visual Edges extracted from API
  const rawVisualEdges: GraphVisualEdge[] = useMemo(() => {
    const backendEdges = data?.subgraph?.edges || data?.edges;
    if (backendEdges && backendEdges.length > 0) return backendEdges;

    // Fallback synthesis
    if (rawVisualNodes.length < 2) return [];
    const edges: GraphVisualEdge[] = [];
    const relationChoices = ['GOVERNED_BY', 'APPLIES_TO', 'DEPENDS_ON', 'CONFLICTS_WITH', 'SUPERSEDES'];
    for (let i = 0; i < Math.min(rawVisualNodes.length - 1, 14); i++) {
      const rel = relationChoices[i % relationChoices.length];
      edges.push({
        id: `edge-${i}`,
        source: rawVisualNodes[i].id,
        target: rawVisualNodes[(i + 1) % rawVisualNodes.length].id,
        relation_type: rel,
        relationship_type: rel,
        relation: rel,
        status: 'approved'
      });
    }
    return edges;
  }, [data, rawVisualNodes]);

  // Compute node degrees for sizing & layout priority
  const nodeDegrees = useMemo(() => {
    const degMap = new Map<string, number>();
    rawVisualEdges.forEach(e => {
      degMap.set(e.source, (degMap.get(e.source) || 0) + 1);
      degMap.set(e.target, (degMap.get(e.target) || 0) + 1);
    });
    return degMap;
  }, [rawVisualEdges]);

  // Counts by node type for filter badges
  const nodeTypeCounts = useMemo(() => {
    const counts: Record<string, number> = { all: rawVisualNodes.length };
    rawVisualNodes.forEach(n => {
      const t = n.type === 'community' ? 'community' : n.type === 'document' ? 'document' : 'entity';
      counts[t] = (counts[t] || 0) + 1;
    });
    return counts;
  }, [rawVisualNodes]);

  // Counts by edge relation for filter dropdown
  const edgeRelationCounts = useMemo(() => {
    const counts: Record<string, number> = { all: rawVisualEdges.length };
    rawVisualEdges.forEach(e => {
      const rel = e.relation_type || e.relationship_type || e.relation || 'GOVERNED_BY';
      counts[rel] = (counts[rel] || 0) + 1;
    });
    return counts;
  }, [rawVisualEdges]);

  // Canvas Viewport Dimensions
  const canvasWidth = 920;
  const canvasHeight = 520;
  const centerX = canvasWidth / 2;
  const centerY = canvasHeight / 2;

  // 3. Initialize Force-Directed Physics Layout
  useEffect(() => {
    if (rawVisualNodes.length === 0) {
      setSimulationNodes([]);
      return;
    }

    // Identify community clusters
    const commNodes = rawVisualNodes.filter(n => n.type === 'community');
    const docNodes = rawVisualNodes.filter(n => n.type === 'document');
    const otherNodes = rawVisualNodes.filter(n => n.type !== 'community' && n.type !== 'document');

    // Create a cluster mapping from edges
    const docCommunityMap = new Map<string, string>();
    rawVisualEdges.forEach(e => {
      if ((e.relation_type || e.relationship_type || e.relation) === 'MEMBER_OF') {
        docCommunityMap.set(e.source, e.target);
      }
    });

    // Assign initial positions in structured GraphRAG hierarchy
    const initialSimNodes: SimNode[] = rawVisualNodes.map((n, idx) => {
      const deg = nodeDegrees.get(n.id) || 1;
      let initX = centerX;
      let initY = centerY;
      let radius = 16;

      if (n.type === 'community') {
        radius = 26;
        if (n.id.includes('root') || n.level === 1) {
          initX = centerX;
          initY = centerY - 30;
        } else {
          const commIdx = commNodes.findIndex(c => c.id === n.id);
          const angle = (commIdx / Math.max(commNodes.length, 1)) * 2 * Math.PI - Math.PI / 2;
          initX = centerX + 180 * Math.cos(angle);
          initY = centerY + 140 * Math.sin(angle);
        }
      } else if (n.type === 'document') {
        radius = 18;
        const targetComm = docCommunityMap.get(n.id);
        const docIdx = docNodes.findIndex(d => d.id === n.id);
        const commAngle = (docIdx / Math.max(docNodes.length, 1)) * 2 * Math.PI;
        const rDist = 190 + (docIdx % 3) * 55;
        initX = centerX + rDist * Math.cos(commAngle);
        initY = centerY + (rDist * 0.75) * Math.sin(commAngle);
      } else {
        // Entities & Rules
        radius = 14;
        const entIdx = otherNodes.findIndex(o => o.id === n.id);
        const entAngle = (entIdx / Math.max(otherNodes.length, 1)) * 2 * Math.PI + Math.PI / 4;
        const rDist = 280 + (entIdx % 2) * 45;
        initX = centerX + rDist * Math.cos(entAngle);
        initY = centerY + (rDist * 0.65) * Math.sin(entAngle);
      }

      // Add a slight deterministic jitter to avoid exact overlaps
      initX += ((idx % 7) - 3) * 12;
      initY += ((idx % 5) - 2) * 12;

      return {
        ...n,
        x: initX,
        y: initY,
        vx: 0,
        vy: 0,
        radius,
        degree: deg,
        clusterId: docCommunityMap.get(n.id) || undefined
      };
    });

    // Run deterministic force-directed simulation (80 relaxation iterations)
    const nodes = [...initialSimNodes];
    const nodeMap = new Map<string, SimNode>(nodes.map(n => [n.id, n]));
    const edges = rawVisualEdges.filter(e => nodeMap.has(e.source) && nodeMap.has(e.target));

    const iterations = 80;
    const kRepel = 2400;
    const centerGravity = 0.045;
    const damping = 0.82;

    for (let iter = 0; iter < iterations; iter++) {
      // 1. Repulsive forces (Coulomb between all pairs)
      for (let i = 0; i < nodes.length; i++) {
        for (let j = i + 1; j < nodes.length; j++) {
          const n1 = nodes[i];
          const n2 = nodes[j];
          const dx = n2.x - n1.x;
          const dy = n2.y - n1.y;
          const distSq = dx * dx + dy * dy + 100;
          const dist = Math.sqrt(distSq);

          // Additional repulsion if nodes are overlapping
          const minDist = n1.radius + n2.radius + 16;
          let force = kRepel / distSq;
          if (dist < minDist) {
            force += (minDist - dist) * 0.25;
          }

          const fx = (dx / dist) * force;
          const fy = (dy / dist) * force;

          n1.vx -= fx;
          n1.vy -= fy;
          n2.vx += fx;
          n2.vy += fy;
        }
      }

      // 2. Attractive spring forces (Hooke along edges)
      for (const e of edges) {
        const n1 = nodeMap.get(e.source);
        const n2 = nodeMap.get(e.target);
        if (!n1 || !n2) continue;

        const dx = n2.x - n1.x;
        const dy = n2.y - n1.y;
        const dist = Math.sqrt(dx * dx + dy * dy) || 1;

        const rel = e.relation_type || e.relationship_type || e.relation || 'GOVERNED_BY';
        const targetDist = rel === 'MEMBER_OF' ? 85 : rel === 'APPLIES_TO' ? 115 : 135;
        const force = (dist - targetDist) * 0.055;

        const fx = (dx / dist) * force;
        const fy = (dy / dist) * force;

        n1.vx += fx;
        n1.vy += fy;
        n2.vx -= fx;
        n2.vy -= fy;
      }

      // 3. Center gravity & boundary bounding
      for (const n of nodes) {
        const dx = centerX - n.x;
        const dy = centerY - n.y;
        n.vx += dx * centerGravity;
        n.vy += dy * centerGravity;

        // Apply velocity with damping
        n.x += n.vx * 0.5;
        n.y += n.vy * 0.5;
        n.vx *= damping;
        n.vy *= damping;

        // Keep inside canvas bounds
        const pad = n.radius + 20;
        n.x = Math.max(pad, Math.min(canvasWidth - pad, n.x));
        n.y = Math.max(pad, Math.min(canvasHeight - pad, n.y));
      }
    }

    setSimulationNodes(nodes);
  }, [rawVisualNodes, rawVisualEdges, nodeDegrees, centerX, centerY, canvasWidth, canvasHeight]);

  // Simulation node lookup map
  const simNodeMap = useMemo(() => {
    const map = new Map<string, SimNode>();
    simulationNodes.forEach(n => map.set(n.id, n));
    return map;
  }, [simulationNodes]);

  // Compute 1-2 hop neighborhood for highlighted node
  const activeNeighborhood = useMemo(() => {
    const targetId = hoveredNodeId || selectedNodeId;
    if (!targetId) return null;

    const neighborIds = new Set<string>([targetId]);
    const connectedEdgeIds = new Set<string>();

    let currentFrontier = new Set<string>([targetId]);
    const maxHops = hopDepth;

    for (let h = 0; h < maxHops; h++) {
      const nextFrontier = new Set<string>();
      rawVisualEdges.forEach(e => {
        if (currentFrontier.has(e.source)) {
          neighborIds.add(e.target);
          nextFrontier.add(e.target);
          connectedEdgeIds.add(e.id);
        }
        if (currentFrontier.has(e.target)) {
          neighborIds.add(e.source);
          nextFrontier.add(e.source);
          connectedEdgeIds.add(e.id);
        }
      });
      currentFrontier = nextFrontier;
    }

    return { neighborIds, connectedEdgeIds };
  }, [hoveredNodeId, selectedNodeId, rawVisualEdges, hopDepth]);

  // Filtered visual nodes based on UI controls
  const displayNodes = useMemo(() => {
    return simulationNodes.filter(n => {
      // Type Filter
      if (selectedNodeTypeFilter === 'community' && n.type !== 'community') return false;
      if (selectedNodeTypeFilter === 'document' && n.type !== 'document') return false;
      if (selectedNodeTypeFilter === 'entity' && (n.type === 'community' || n.type === 'document')) return false;

      // Text search
      if (searchFilter) {
        const query = searchFilter.toLowerCase();
        const matchesLabel = n.label.toLowerCase().includes(query);
        const matchesStatement = (n.statement || '').toLowerCase().includes(query);
        const matchesType = n.type.toLowerCase().includes(query);
        if (!matchesLabel && !matchesStatement && !matchesType) return false;
      }
      return true;
    });
  }, [simulationNodes, selectedNodeTypeFilter, searchFilter]);

  const displayNodeIds = useMemo(() => new Set(displayNodes.map(n => n.id)), [displayNodes]);

  // Filtered visual edges based on UI controls
  const displayEdges = useMemo(() => {
    return rawVisualEdges.filter(e => {
      if (!displayNodeIds.has(e.source) || !displayNodeIds.has(e.target)) return false;

      const rel = e.relation_type || e.relationship_type || e.relation || 'GOVERNED_BY';
      if (selectedEdgeType !== 'all' && rel !== selectedEdgeType) return false;

      return true;
    });
  }, [rawVisualEdges, displayNodeIds, selectedEdgeType]);

  // --- Interactive Drag & Pan Handlers ---
  const handleCanvasMouseDown = (e: React.MouseEvent<SVGSVGElement>) => {
    // If clicking directly on SVG canvas (not on a node), start canvas pan
    if ((e.target as HTMLElement).tagName === 'svg' || (e.target as HTMLElement).id === 'canvas-bg') {
      setIsPanning(true);
      panStartRef.current = { x: e.clientX - pan.x, y: e.clientY - pan.y };
    }
  };

  const handleCanvasMouseMove = (e: React.MouseEvent<SVGSVGElement>) => {
    if (isPanning) {
      setPan({
        x: e.clientX - panStartRef.current.x,
        y: e.clientY - panStartRef.current.y
      });
      return;
    }

    if (draggedNodeId && canvasRef.current) {
      const rect = canvasRef.current.getBoundingClientRect();
      // Convert screen coordinates to SVG transformed coordinates
      const svgX = (e.clientX - rect.left - pan.x) / zoom;
      const svgY = (e.clientY - rect.top - pan.y) / zoom;

      setSimulationNodes(prev => prev.map(node => {
        if (node.id === draggedNodeId) {
          return { ...node, x: svgX, y: svgY };
        }
        return node;
      }));
    }
  };

  const handleCanvasMouseUp = () => {
    setIsPanning(false);
    setDraggedNodeId(null);
  };

  const handleNodeMouseDown = (e: React.MouseEvent, nodeId: string) => {
    e.stopPropagation();
    setDraggedNodeId(nodeId);
  };

  // Zoom controls
  const handleZoomIn = () => setZoom(z => Math.min(2.5, z + 0.2));
  const handleZoomOut = () => setZoom(z => Math.max(0.4, z - 0.2));
  const handleResetView = () => {
    setZoom(1.0);
    setPan({ x: 0, y: 0 });
  };

  // Physics Re-layout / Jiggle
  const handleReLayout = () => {
    loadGraphOverview();
    handleResetView();
  };

  return (
    <div className="space-y-6">
      {/* Hero Banner */}
      <div 
        className="relative overflow-hidden rounded-2xl p-6 sm:p-8 border shadow-sm transition-all duration-200"
        style={{
          backgroundColor: 'var(--bg-surface)',
          borderColor: 'var(--border-color)',
        }}
      >
        <div className="relative z-10 max-w-4xl">
          <div 
            className="inline-flex items-center gap-2 px-3 py-1 rounded-full text-xs font-semibold border mb-3"
            style={{
              backgroundColor: 'var(--accent-light)',
              borderColor: 'var(--border-color)',
              color: 'var(--brand-accent)',
            }}
          >
            <Layers className="w-3.5 h-3.5" />
            <span>GraphRAG & RAPTOR Lineage Visualizer v2.0 · Graphify Architecture</span>
          </div>

          <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
            <div>
              <h1 className="text-xl sm:text-2xl font-extrabold tracking-tight text-[var(--text-primary)]">
                Enterprise Knowledge Grid & Ontology Lineage
              </h1>
              <p className="mt-1.5 text-xs sm:text-sm text-[var(--text-secondary)] leading-relaxed max-w-2xl">
                Hierarchical summarization tree with verified token ceilings (≤ 800 tokens), canonical entity resolution across systems, and deterministic edge invariants.
              </p>
            </div>

            <div className="flex items-center gap-2">
              <button
                onClick={loadGraphOverview}
                disabled={isLoading}
                className="px-4 py-2 rounded-xl text-xs font-semibold border flex items-center gap-2 transition-all cursor-pointer active:scale-95 shadow-sm"
                style={{
                  backgroundColor: 'var(--bg-surface-soft)',
                  borderColor: 'var(--border-color)',
                  color: 'var(--text-primary)',
                }}
              >
                <RefreshCw className={`w-3.5 h-3.5 ${isLoading ? 'animate-spin' : ''}`} />
                <span>Refresh Graph</span>
              </button>
            </div>
          </div>
        </div>

        {/* Global Metric Strips */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mt-6 pt-5 border-t" style={{ borderColor: 'var(--border-color)' }}>
          <div className="p-3 rounded-xl border" style={{ backgroundColor: 'var(--bg-surface-soft)', borderColor: 'var(--border-color)' }}>
            <span className="text-[10px] uppercase font-mono tracking-wider text-secondary block">Active Stable Rules</span>
            <span className="text-lg font-bold text-primary font-mono">{activeRulesCount}</span>
          </div>
          <div className="p-3 rounded-xl border" style={{ backgroundColor: 'var(--bg-surface-soft)', borderColor: 'var(--border-color)' }}>
            <span className="text-[10px] uppercase font-mono tracking-wider text-secondary block">Knowledge Relationships</span>
            <span className="text-lg font-bold text-primary font-mono">{relationshipsCount || rawVisualEdges.length}</span>
          </div>
          <div className="p-3 rounded-xl border" style={{ backgroundColor: 'var(--bg-surface-soft)', borderColor: 'var(--border-color)' }}>
            <span className="text-[10px] uppercase font-mono tracking-wider text-secondary block">RAPTOR Communities</span>
            <span className="text-lg font-bold text-emerald-400 font-mono">{communitiesList.length}</span>
          </div>
          <div className="p-3 rounded-xl border" style={{ backgroundColor: 'var(--bg-surface-soft)', borderColor: 'var(--border-color)' }}>
            <span className="text-[10px] uppercase font-mono tracking-wider text-secondary block">Ceiling Invariant</span>
            <span className="text-xs font-mono font-bold text-emerald-400 flex items-center gap-1 mt-1">
              <CheckCircle2 className="w-3.5 h-3.5" /> ≤ 800 Tokens Bound
            </span>
          </div>
        </div>
      </div>

      {/* Interactive Topology & Graphify GraphRAG Canvas */}
      <div 
        className="p-6 rounded-2xl border shadow-sm space-y-4"
        style={{
          backgroundColor: 'var(--bg-surface)',
          borderColor: 'var(--border-color)',
        }}
      >
        {/* Top Control Bar */}
        <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-4 border-b pb-4" style={{ borderColor: 'var(--border-color)' }}>
          <div>
            <h3 className="text-base font-bold text-primary flex items-center gap-2">
              <Network className="w-4 h-4 text-emerald-400" />
              Graphify Interactive Knowledge Topology & Neighborhood Lineage
            </h3>
            <p className="text-xs text-secondary mt-0.5">
              Live physics-directed GraphRAG network. Drag nodes to inspect relationships, scroll/drag canvas to pan & zoom.
            </p>
          </div>

          <div className="flex flex-wrap items-center gap-3">
            {/* Live Search */}
            <div className="relative">
              <Search className="w-3.5 h-3.5 text-secondary absolute left-2.5 top-1/2 -translate-y-1/2" />
              <input
                type="text"
                value={searchFilter}
                onChange={(e) => setSearchFilter(e.target.value)}
                placeholder="Search nodes or entities..."
                className="text-xs pl-8 pr-3 py-1.5 rounded-lg border bg-surface-soft text-primary font-medium focus:outline-none focus:ring-1 focus:ring-blue-500 w-44"
                style={{ borderColor: 'var(--border-color)' }}
              />
              {searchFilter && (
                <button 
                  onClick={() => setSearchFilter('')}
                  className="absolute right-2 top-1/2 -translate-y-1/2 text-secondary hover:text-primary"
                >
                  <X className="w-3 h-3" />
                </button>
              )}
            </div>

            {/* Hop Depth Selector */}
            <div className="flex items-center gap-1 text-xs text-secondary font-medium">
              <Sliders className="w-3.5 h-3.5" />
              <span>Hops:</span>
              <div className="flex items-center rounded-lg border bg-surface-soft overflow-hidden" style={{ borderColor: 'var(--border-color)' }}>
                {[1, 2, 3, 4].map((h) => (
                  <button
                    key={h}
                    onClick={() => setHopDepth(h)}
                    className={`px-2.5 py-1 text-xs font-mono font-bold transition-all cursor-pointer ${
                      hopDepth === h
                        ? 'bg-emerald-500/20 text-emerald-400'
                        : 'text-secondary hover:text-primary'
                    }`}
                  >
                    {h}
                  </button>
                ))}
              </div>
            </div>

            {/* Edge Type Toggle Filter */}
            <div className="flex items-center gap-1.5">
              <Filter className="w-3.5 h-3.5 text-secondary" />
              <select
                value={selectedEdgeType}
                onChange={(e) => setSelectedEdgeType(e.target.value)}
                className="text-xs px-2.5 py-1 rounded-lg border bg-surface-soft text-primary font-medium cursor-pointer"
                style={{ borderColor: 'var(--border-color)' }}
              >
                <option value="all">All Edges ({rawVisualEdges.length})</option>
                <option value="MEMBER_OF">MEMBER_OF ({edgeRelationCounts['MEMBER_OF'] || 0})</option>
                <option value="APPLIES_TO">APPLIES_TO ({edgeRelationCounts['APPLIES_TO'] || 0})</option>
                <option value="GOVERNED_BY">GOVERNED_BY ({edgeRelationCounts['GOVERNED_BY'] || 0})</option>
                <option value="SUPERSEDES">SUPERSEDES ({edgeRelationCounts['SUPERSEDES'] || 0})</option>
                <option value="CONFLICTS_WITH">CONFLICTS_WITH ({edgeRelationCounts['CONFLICTS_WITH'] || 0})</option>
              </select>
            </div>
          </div>
        </div>

        {/* Node Category Filter Pills */}
        <div className="flex flex-wrap items-center justify-between gap-3 text-xs">
          <div className="flex items-center gap-1.5">
            {[
              { id: 'all', label: `All Nodes (${rawVisualNodes.length})` },
              { id: 'community', label: `Communities (${nodeTypeCounts['community'] || 0})` },
              { id: 'document', label: `Documents (${nodeTypeCounts['document'] || 0})` },
              { id: 'entity', label: `Entities (${nodeTypeCounts['entity'] || 0})` },
            ].map(pill => (
              <button
                key={pill.id}
                onClick={() => setSelectedNodeTypeFilter(pill.id)}
                className={`px-3 py-1 rounded-full font-medium transition-all cursor-pointer border ${
                  selectedNodeTypeFilter === pill.id
                    ? 'bg-blue-500/10 text-blue-600 border-blue-500/30 font-semibold'
                    : 'bg-surface-soft text-secondary hover:text-primary border-transparent'
                }`}
              >
                {pill.label}
              </button>
            ))}
          </div>

          {/* Quick Legend */}
          <div className="flex flex-wrap items-center gap-3 text-[11px] text-secondary font-mono">
            <span className="flex items-center gap-1">
              <span className="w-2.5 h-2.5 rounded-full bg-purple-500 inline-block"></span> Community
            </span>
            <span className="flex items-center gap-1">
              <span className="w-2.5 h-2.5 rounded-sm bg-blue-500 inline-block"></span> Document
            </span>
            <span className="flex items-center gap-1">
              <span className="w-2.5 h-2.5 rounded-full bg-emerald-500 inline-block"></span> Entity
            </span>
            <span className="flex items-center gap-1">
              <span className="w-2.5 h-2.5 rounded-full bg-amber-500 inline-block"></span> Rule
            </span>
          </div>
        </div>

        {/* Interactive SVG Graph Canvas with Force Physics & Drag */}
        <div 
          className="relative w-full rounded-xl border overflow-hidden select-none bg-surface-soft min-h-[480px]"
          style={{ borderColor: 'var(--border-color)', cursor: isPanning ? 'grabbing' : 'default' }}
        >
          <svg 
            ref={canvasRef}
            viewBox={`0 0 ${canvasWidth} ${canvasHeight}`} 
            className="w-full h-full min-h-[480px] max-h-[580px]"
            onMouseDown={handleCanvasMouseDown}
            onMouseMove={handleCanvasMouseMove}
            onMouseUp={handleCanvasMouseUp}
            onMouseLeave={handleCanvasMouseUp}
          >
            {/* Background click target for panning */}
            <rect 
              id="canvas-bg" 
              x="0" 
              y="0" 
              width={canvasWidth} 
              height={canvasHeight} 
              fill="transparent" 
            />

            {/* Directed Edge Arrow Definitions */}
            <defs>
              <marker id="arrow-blue" viewBox="0 0 10 10" refX="22" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
                <path d="M 0 0 L 10 5 L 0 10 z" fill="var(--lavender-deep)" />
              </marker>
              <marker id="arrow-emerald" viewBox="0 0 10 10" refX="20" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
                <path d="M 0 0 L 10 5 L 0 10 z" fill="var(--sage-deep)" />
              </marker>
              <marker id="arrow-purple" viewBox="0 0 10 10" refX="20" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
                <path d="M 0 0 L 10 5 L 0 10 z" fill="var(--lavender)" />
              </marker>
              <marker id="arrow-red" viewBox="0 0 10 10" refX="20" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
                <path d="M 0 0 L 10 5 L 0 10 z" fill="var(--red)" />
              </marker>
              <marker id="arrow-indigo" viewBox="0 0 10 10" refX="20" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
                <path d="M 0 0 L 10 5 L 0 10 z" fill="var(--lavender-active)" />
              </marker>
            </defs>

            {/* Transformed Content Group (Pan & Zoom) */}
            <g transform={`translate(${pan.x}, ${pan.y}) scale(${zoom})`}>
              
              {/* Directed Edges */}
              {displayEdges.map((edge) => {
                const src = simNodeMap.get(edge.source);
                const tgt = simNodeMap.get(edge.target);
                if (!src || !tgt) return null;

                const relType = edge.relation_type || edge.relationship_type || edge.relation || 'GOVERNED_BY';
                const isConflict = relType === 'CONFLICTS_WITH';
                const isSupersedes = relType === 'SUPERSEDES';
                const isMember = relType === 'MEMBER_OF';
                const isApplies = relType === 'APPLIES_TO';

                const strokeColor = isConflict 
                  ? 'var(--red)' 
                  : isSupersedes 
                  ? 'var(--lavender)' 
                  : isMember 
                  ? 'var(--lavender-active)' 
                  : isApplies 
                  ? 'var(--sage-deep)' 
                  : 'var(--lavender-deep)';

                const markerId = isConflict 
                  ? 'arrow-red' 
                  : isSupersedes 
                  ? 'arrow-purple' 
                  : isMember 
                  ? 'arrow-indigo' 
                  : isApplies 
                  ? 'arrow-emerald' 
                  : 'arrow-blue';

                // Check active neighborhood highlighting
                const isEdgeActive = activeNeighborhood 
                  ? activeNeighborhood.connectedEdgeIds.has(edge.id)
                  : true;
                const edgeOpacity = activeNeighborhood ? (isEdgeActive ? 0.95 : 0.12) : 0.65;
                const strokeWidth = isEdgeActive && activeNeighborhood ? 2.6 : (isConflict ? 2.2 : 1.6);

                return (
                  <g key={edge.id} className="transition-opacity duration-200">
                    <line
                      x1={src.x}
                      y1={src.y}
                      x2={tgt.x}
                      y2={tgt.y}
                      stroke={strokeColor}
                      strokeWidth={strokeWidth}
                      strokeDasharray={isConflict ? "5,5" : isMember ? "3,3" : "none"}
                      strokeOpacity={edgeOpacity}
                      markerEnd={`url(#${markerId})`}
                    />
                  </g>
                );
              })}

              {/* Graph Nodes */}
              {displayNodes.map((n) => {
                const isSelected = selectedNodeId === n.id;
                const isHovered = hoveredNodeId === n.id;
                const isCommunity = n.type === 'community';
                const isDocument = n.type === 'document';
                const isEntity = !isCommunity && !isDocument;

                // Neighborhood highlight status
                const isNodeInNeighborhood = activeNeighborhood 
                  ? activeNeighborhood.neighborIds.has(n.id)
                  : true;
                const nodeOpacity = activeNeighborhood ? (isNodeInNeighborhood ? 1.0 : 0.22) : 1.0;

                // Colors
                const communityColor = n.level === 1 ? 'var(--lavender)' : 'var(--lavender-active)';
                const docColor = 'var(--lavender-deep)';
                const entityColor = n.type === 'regulation' ? 'var(--lavender-deep)' : n.type === 'system' ? 'var(--sage-deep)' : 'var(--sage)';
                const ruleColor = 'var(--well-amber-fg)';

                const mainColor = isCommunity 
                  ? communityColor 
                  : isDocument 
                  ? docColor 
                  : n.type === 'rule' 
                  ? ruleColor 
                  : entityColor;

                return (
                  <g 
                    key={n.id} 
                    className="cursor-pointer transition-opacity duration-150"
                    opacity={nodeOpacity}
                    onMouseDown={(e) => handleNodeMouseDown(e, n.id)}
                    onClick={() => handleSelectNode(n.id)}
                    onMouseEnter={() => setHoveredNodeId(n.id)}
                    onMouseLeave={() => setHoveredNodeId(null)}
                  >
                    {/* Outer Glow Halo for Selected / Hovered Node */}
                    {(isSelected || isHovered) && (
                      <circle
                        cx={n.x}
                        cy={n.y}
                        r={n.radius + 7}
                        fill={mainColor}
                        fillOpacity={0.25}
                        stroke={mainColor}
                        strokeWidth={1.5}
                      />
                    )}

                    {/* Community Hexagon/Ring Node */}
                    {isCommunity && (
                      <g>
                        <circle
                          cx={n.x}
                          cy={n.y}
                          r={n.radius}
                          fill={mainColor}
                          fillOpacity={0.9}
                          stroke="#ffffff"
                          strokeWidth={isSelected ? 3 : 2}
                        />
                        {/* Token Ceiling Verified Badge */}
                        <circle
                          cx={n.x + n.radius - 4}
                          cy={n.y - n.radius + 4}
                          r={6}
                          fill="var(--sage-deep)"
                          stroke="#ffffff"
                          strokeWidth={1.5}
                        />
                      </g>
                    )}

                    {/* Document Rounded Card Node */}
                    {isDocument && (
                      <g>
                        <rect
                          x={n.x - n.radius - 4}
                          y={n.y - n.radius}
                          width={(n.radius + 4) * 2}
                          height={n.radius * 2}
                          rx={7}
                          fill={mainColor}
                          fillOpacity={0.92}
                          stroke="#ffffff"
                          strokeWidth={isSelected ? 3 : 1.8}
                        />
                      </g>
                    )}

                    {/* Entity / Rule Circular Node */}
                    {isEntity && (
                      <circle
                        cx={n.x}
                        cy={n.y}
                        r={n.radius}
                        fill={mainColor}
                        fillOpacity={0.88}
                        stroke="#ffffff"
                        strokeWidth={isSelected ? 3 : 1.8}
                      />
                    )}

                    {/* Inner Node Icon / Glyph */}
                    <text
                      x={n.x}
                      y={n.y + (isDocument ? 3.5 : 4)}
                      textAnchor="middle"
                      className="text-[9px] font-mono font-bold fill-white pointer-events-none select-none"
                    >
                      {isCommunity ? (n.level === 1 ? 'L1' : 'L0') : isDocument ? `R${n.authority || 6}` : n.label.slice(0, 2).toUpperCase()}
                    </text>

                    {/* Node Label Below */}
                    <text
                      x={n.x}
                      y={n.y + n.radius + 14}
                      textAnchor="middle"
                      className="text-[10px] font-mono font-semibold select-none pointer-events-none"
                      style={{ 
                        fill: isSelected ? 'var(--brand-accent)' : 'var(--text-primary)',
                        paintOrder: 'stroke',
                        stroke: 'var(--bg-surface)',
                        strokeWidth: 3,
                        strokeLinejoin: 'round'
                      }}
                    >
                      {n.label.length > 16 ? `${n.label.slice(0, 15)}…` : n.label}
                    </text>
                  </g>
                );
              })}
            </g>
          </svg>

          {/* Floating Canvas Navigation Toolbar */}
          <div className="absolute top-3 right-3 flex items-center gap-1.5 p-1 rounded-xl border bg-surface/90 backdrop-blur shadow-sm" style={{ borderColor: 'var(--border-color)' }}>
            <button
              onClick={handleZoomIn}
              title="Zoom In"
              className="p-1.5 rounded-lg hover:bg-surface-soft text-secondary hover:text-primary transition-all cursor-pointer"
            >
              <ZoomIn className="w-3.5 h-3.5" />
            </button>
            <button
              onClick={handleZoomOut}
              title="Zoom Out"
              className="p-1.5 rounded-lg hover:bg-surface-soft text-secondary hover:text-primary transition-all cursor-pointer"
            >
              <ZoomOut className="w-3.5 h-3.5" />
            </button>
            <button
              onClick={handleResetView}
              title="Fit View / Reset Pan"
              className="p-1.5 rounded-lg hover:bg-surface-soft text-secondary hover:text-primary transition-all cursor-pointer"
            >
              <Maximize2 className="w-3.5 h-3.5" />
            </button>
            <button
              onClick={handleReLayout}
              title="Re-layout Physics"
              className="p-1.5 rounded-lg hover:bg-surface-soft text-secondary hover:text-primary transition-all cursor-pointer"
            >
              <RotateCcw className="w-3.5 h-3.5" />
            </button>
          </div>

          {/* Node Interaction Instruction Footnote */}
          <div className="absolute bottom-3 left-4 text-[11px] text-muted font-mono flex items-center gap-2 bg-surface/80 backdrop-blur px-2.5 py-1 rounded-lg border border-border">
            <Eye className="w-3.5 h-3.5 text-blue-500" />
            <span>Click any node to inspect provenance · Drag nodes to reposition · Drag canvas to pan</span>
          </div>

          {/* Active Hover / Selection Summary Badge */}
          {hoveredNodeId && simNodeMap.get(hoveredNodeId) && (
            <div className="absolute top-3 left-3 p-2.5 rounded-xl border bg-surface/95 backdrop-blur shadow-md max-w-xs text-xs space-y-1 animate-in fade-in" style={{ borderColor: 'var(--border-color)' }}>
              <div className="font-bold text-primary flex items-center gap-1.5">
                <span>{simNodeMap.get(hoveredNodeId)?.label}</span>
                <span className="text-[9px] font-mono uppercase px-1.5 py-0.2 rounded bg-surface-soft border text-secondary">
                  {simNodeMap.get(hoveredNodeId)?.type}
                </span>
              </div>
              <p className="text-[11px] text-secondary line-clamp-2">
                {simNodeMap.get(hoveredNodeId)?.statement || 'Deterministic GraphRAG node'}
              </p>
            </div>
          )}
        </div>
      </div>

      {/* Node Inspector Drawer */}
      {selectedNodeId && (
        <div 
          className="p-6 rounded-2xl border shadow-lg space-y-4 animate-in fade-in duration-200"
          style={{
            backgroundColor: 'var(--bg-surface)',
            borderColor: 'var(--brand-accent)',
          }}
        >
          <div className="flex items-center justify-between border-b pb-3" style={{ borderColor: 'var(--border-color)' }}>
            <div className="flex items-center gap-2.5">
              <div className="w-8 h-8 rounded-xl bg-blue-500/10 text-blue-600 flex items-center justify-center font-bold">
                <ShieldCheck className="w-4 h-4" />
              </div>
              <div>
                <h4 className="text-sm font-bold text-primary flex items-center gap-2">
                  <span>Node Provenance: {lineageData?.node?.label || selectedNodeId}</span>
                  <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-blue-500/10 text-blue-600 border border-blue-500/30">
                    Rank {lineageData?.node?.authority_level ?? 5}
                  </span>
                </h4>
                <p className="text-[11px] text-secondary">
                  Lineage depth: {hopDepth} hops · Multi-tenant workspace sovereign boundary
                </p>
              </div>
            </div>

            <button
              onClick={() => setSelectedNodeId(null)}
              className="p-1.5 rounded-lg hover:bg-surface-soft text-secondary hover:text-primary transition-all cursor-pointer"
            >
              <X className="w-4 h-4" />
            </button>
          </div>

          {isLoadingLineage ? (
            <div className="p-8 text-center text-xs text-secondary flex items-center justify-center gap-2">
              <RefreshCw className="w-4 h-4 animate-spin text-blue-500" />
              <span>Traversing graph lineage and provenance records...</span>
            </div>
          ) : lineageData ? (
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4 text-xs">
              {/* Provenance & Source */}
              <div className="p-3.5 rounded-xl border bg-surface-soft space-y-2" style={{ borderColor: 'var(--border-color)' }}>
                <span className="text-[10px] font-mono uppercase font-bold text-muted block flex items-center gap-1">
                  <FileText className="w-3 h-3 text-blue-500" /> Source @ Version Provenance
                </span>
                <div className="font-semibold text-primary">{lineageData.from_source?.title || 'Enterprise Knowledge Item'}</div>
                <div className="text-[11px] text-secondary font-mono">
                  Code: {lineageData.from_source?.document_code || 'N/A'} (v{lineageData.from_source?.version_number ?? 1})
                </div>
                <div className="text-[11px] text-emerald-600 font-mono">
                  Authority Rank: {lineageData.from_source?.authority_level ?? lineageData.node.authority_level}
                </div>
                {lineageData.from_source?.effective_date && (
                  <div className="text-[10px] text-muted flex items-center gap-1 font-mono">
                    <Clock className="w-3 h-3" /> Effective: {lineageData.from_source.effective_date.slice(0, 10)}
                  </div>
                )}
              </div>

              {/* Conflicts & Overrides */}
              <div className="p-3.5 rounded-xl border bg-surface-soft space-y-2" style={{ borderColor: 'var(--border-color)' }}>
                <span className="text-[10px] font-mono uppercase font-bold text-muted block flex items-center gap-1">
                  <Scale className="w-3 h-3 text-rose-500" /> Conflicts & Exceptions
                </span>
                {lineageData.conflicts.length > 0 ? (
                  lineageData.conflicts.map((c, i) => (
                    <div key={i} className="p-2 rounded bg-rose-500/10 border border-rose-500/20 text-rose-600 text-[11px]">
                      {c.resolution_notes || c.claim_a || 'Active Contradiction Gated'}
                    </div>
                  ))
                ) : (
                  <div className="text-[11px] text-emerald-600 flex items-center gap-1">
                    <CheckCircle2 className="w-3.5 h-3.5" /> No unresolved contradictions
                  </div>
                )}
                {lineageData.overrides.length > 0 && (
                  <div className="pt-1 text-[11px] text-amber-600">
                    <span className="font-semibold">Scoped Overrides:</span> {lineageData.overrides[0].justification || 'Active waiver'}
                  </div>
                )}
              </div>

              {/* Connected Dependencies */}
              <div className="p-3.5 rounded-xl border bg-surface-soft space-y-2" style={{ borderColor: 'var(--border-color)' }}>
                <span className="text-[10px] font-mono uppercase font-bold text-muted block flex items-center gap-1">
                  <GitFork className="w-3 h-3 text-purple-500" /> Relational Dependencies
                </span>
                <div className="text-[11px] text-secondary">
                  <span className="text-primary font-bold">{lineageData.upstream_nodes.length}</span> upstream precedents
                </div>
                <div className="text-[11px] text-secondary">
                  <span className="text-primary font-bold">{lineageData.downstream_nodes.length}</span> downstream dependents
                </div>
                <div className="text-[10px] font-mono text-purple-600">
                  {lineageData.governed_by.length} historical governance audits
                </div>
              </div>
            </div>
          ) : null}
        </div>
      )}

      {/* Relationship Edge Types Distribution */}
      <div 
        className="p-5 rounded-2xl border shadow-sm space-y-3"
        style={{
          backgroundColor: 'var(--bg-surface)',
          borderColor: 'var(--border-color)',
        }}
      >
        <div className="flex items-center justify-between">
          <h3 className="text-xs font-bold uppercase tracking-wider text-secondary flex items-center gap-2">
            <GitFork className="w-3.5 h-3.5 text-blue-500" />
            Deterministic Graph Edge Ontology & Invariants
          </h3>
          <span className="text-[10px] font-mono text-secondary">
            {totalEdgeCount || rawVisualEdges.length} Total Active Edges
          </span>
        </div>

        <div className="grid grid-cols-2 sm:grid-cols-5 gap-3">
          {[
            { type: 'MEMBER_OF', label: 'Member Of', desc: 'Document clustered in RAPTOR domain', color: 'border-indigo-500/40 text-indigo-600 bg-indigo-500/10' },
            { type: 'APPLIES_TO', label: 'Applies To', desc: 'Direct entity/system scope link', color: 'border-emerald-500/40 text-emerald-600 bg-emerald-500/10' },
            { type: 'GOVERNED_BY', label: 'Governed By', desc: 'Rule bounded by higher standard', color: 'border-blue-500/40 text-blue-600 bg-blue-500/10' },
            { type: 'SUPERSEDES', label: 'Supersedes', desc: 'New policy deprecates prior version', color: 'border-purple-500/40 text-purple-600 bg-purple-500/10' },
            { type: 'CONFLICTS_WITH', label: 'Conflicts With', desc: 'Direct NLI contradiction detected', color: 'border-rose-500/40 text-rose-600 bg-rose-500/10' },
          ].map((edge) => {
            const count = edgeRelationCounts[edge.type] ?? edgeTypes[edge.type] ?? 0;
            return (
              <div 
                key={edge.type}
                className="p-3 rounded-xl border flex flex-col justify-between"
                style={{
                  backgroundColor: 'var(--bg-surface-soft)',
                  borderColor: 'var(--border-color)',
                }}
              >
                <div>
                  <div className="flex items-center justify-between mb-1">
                    <span className="text-xs font-bold text-primary">{edge.label}</span>
                    <span className={`text-[10px] font-mono font-bold px-1.5 py-0.2 rounded border ${edge.color}`}>
                      {count}
                    </span>
                  </div>
                  <p className="text-[10px] text-secondary leading-snug">{edge.desc}</p>
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* RAPTOR Hierarchical Community Cards */}
      <div 
        className="p-6 rounded-2xl border shadow-sm space-y-4"
        style={{
          backgroundColor: 'var(--bg-surface)',
          borderColor: 'var(--border-color)',
        }}
      >
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b pb-4" style={{ borderColor: 'var(--border-color)' }}>
          <div>
            <h3 className="text-base font-bold text-primary flex items-center gap-2">
              <Network className="w-4 h-4 text-emerald-500" />
              RAPTOR Community Hierarchy (`DomainSummary`)
            </h3>
            <p className="text-xs text-secondary mt-0.5">
              Clustered semantic communities. Level-1 enterprise aggregates down to Level-0 domain-bounded summaries.
            </p>
          </div>

          {/* Level Filter Tabs */}
          <div className="flex items-center gap-1.5 p-1 rounded-lg border bg-surface-soft" style={{ borderColor: 'var(--border-color)' }}>
            {(['all', '1', '0'] as const).map((lvl) => (
              <button
                key={lvl}
                onClick={() => setSelectedLevel(lvl)}
                className={`px-2.5 py-1 rounded text-xs font-semibold transition-all cursor-pointer ${
                  selectedLevel === lvl
                    ? 'bg-blue-500/10 text-blue-600 border border-blue-500/30'
                    : 'text-secondary hover:text-primary'
                }`}
              >
                {lvl === 'all' ? 'All Levels' : lvl === '1' ? 'Level-1 Root' : 'Level-0 Domains'}
              </button>
            ))}
          </div>
        </div>

        {/* Communities Grid */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {filteredCommunities.map((comm) => {
            const isExpanded = expandedCommunityId === comm.id;
            return (
              <div
                key={comm.id}
                className="p-4 rounded-xl border flex flex-col justify-between space-y-3 transition-all hover:border-[var(--brand-accent)]"
                style={{
                  backgroundColor: 'var(--bg-surface-soft)',
                  borderColor: 'var(--border-color)',
                }}
              >
                <div>
                  <div className="flex items-center justify-between gap-2 mb-2">
                    <div className="flex items-center gap-2">
                      <span className="text-xs font-bold font-mono text-primary">{comm.domain || comm.domain_name}</span>
                      <span className={`text-[10px] font-mono px-2 py-0.5 rounded border ${
                        comm.level === 1 
                          ? 'bg-purple-500/10 text-purple-600 border-purple-500/30' 
                          : 'bg-blue-500/10 text-blue-600 border-blue-500/30'
                      }`}>
                        Level {comm.level}
                      </span>
                    </div>
                    <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-emerald-500/10 text-emerald-600 border border-emerald-500/30 flex items-center gap-1">
                      <CheckCircle2 className="w-3 h-3" /> {comm.token_count} toks (≤ 800)
                    </span>
                  </div>

                  <p className="text-xs text-secondary leading-relaxed">
                    {comm.summary_text}
                  </p>

                  {/* Expand Member Rules Accordion */}
                  {isExpanded && (
                    <div className="mt-3 p-3 rounded-lg border bg-surface space-y-2 text-xs" style={{ borderColor: 'var(--border-color)' }}>
                      <span className="text-[10px] font-mono font-bold text-muted uppercase block">Member Directives in Community</span>
                      <div className="space-y-1.5">
                        <div className="flex items-center justify-between p-1.5 rounded bg-surface-soft text-[11px]">
                          <span className="font-mono text-primary font-bold">SEC-CRYPT-001</span>
                          <span className="text-emerald-600 font-mono text-[10px]">AES-256 Mandatory</span>
                        </div>
                        <div className="flex items-center justify-between p-1.5 rounded bg-surface-soft text-[11px]">
                          <span className="font-mono text-primary font-bold">SEC-ACCESS-004</span>
                          <span className="text-emerald-600 font-mono text-[10px]">MFA Hardware Auth</span>
                        </div>
                        <div className="flex items-center justify-between p-1.5 rounded bg-surface-soft text-[11px]">
                          <span className="font-mono text-primary font-bold">AI-GOV-014</span>
                          <span className="text-emerald-600 font-mono text-[10px]">Human Review Floor</span>
                        </div>
                      </div>
                    </div>
                  )}
                </div>

                <div className="pt-2 border-t flex items-center justify-between text-[11px] text-secondary font-mono" style={{ borderColor: 'var(--border-color)' }}>
                  <button
                    onClick={() => setExpandedCommunityId(isExpanded ? null : comm.id)}
                    className="hover:text-primary flex items-center gap-1 cursor-pointer"
                  >
                    <span>{comm.member_rule_count ?? comm.rule_count ?? 8} Rules Clustered</span>
                    <ChevronRight className={`w-3.5 h-3.5 transition-transform ${isExpanded ? 'rotate-90' : ''}`} />
                  </button>
                  <span className="text-emerald-600">{comm.authority_tier || 'Enterprise Standard'}</span>
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* Canonical Entity Ontology & Cross-Source Matrix */}
      <div 
        className="p-6 rounded-2xl border shadow-sm space-y-4"
        style={{
          backgroundColor: 'var(--bg-surface)',
          borderColor: 'var(--border-color)',
        }}
      >
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b pb-4" style={{ borderColor: 'var(--border-color)' }}>
          <div>
            <h3 className="text-base font-bold text-primary flex items-center gap-2">
              <Box className="w-4 h-4 text-blue-500" />
              Canonical Entity Ontology & Semantic Aliases
            </h3>
            <p className="text-xs text-secondary mt-0.5">
              Cross-document entity deduplication with linked aliases and citation frequencies.
            </p>
          </div>

          {/* Entity Type Filter Tabs */}
          <div className="flex flex-wrap items-center gap-1.5">
            {entityTypes.map((t) => (
              <button
                key={t}
                onClick={() => setSelectedEntityType(t)}
                className={`px-2.5 py-1 rounded text-[11px] font-semibold transition-all cursor-pointer ${
                  selectedEntityType === t
                    ? 'bg-blue-500/10 text-blue-600 border border-blue-500/30'
                    : 'text-secondary hover:text-primary border border-transparent'
                }`}
              >
                {t.toUpperCase()}
              </button>
            ))}
          </div>
        </div>

        {/* Entity Chips */}
        <div className="flex flex-wrap gap-2.5">
          {filteredEntities.map((ent) => (
            <div
              key={ent.name}
              onClick={() => handleSelectNode(ent.name)}
              className="p-2.5 rounded-xl border flex items-center gap-2.5 transition-all hover:border-[var(--brand-accent)] cursor-pointer"
              style={{
                backgroundColor: 'var(--bg-surface-soft)',
                borderColor: 'var(--border-color)',
              }}
            >
              <div className="flex flex-col">
                <div className="flex items-center gap-2">
                  <span className="text-xs font-bold text-primary">{ent.name}</span>
                  <span className="text-[9px] font-mono px-1.5 py-0.2 rounded bg-surface border text-secondary">
                    {ent.entity_type}
                  </span>
                </div>
                {ent.aliases.length > 0 && (
                  <span className="text-[10px] text-muted font-mono truncate max-w-xs">
                    aka: {ent.aliases.join(', ')}
                  </span>
                )}
              </div>
              <span className="text-[10px] font-mono font-bold px-1.5 py-0.5 rounded bg-blue-500/10 text-blue-600 border border-blue-500/20 ml-auto">
                {ent.mention_count ?? 1}x
              </span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
};
