'use client';

import React, { useState } from 'react';
import { 
  FileText, 
  Layers, 
  Cpu, 
  Database, 
  ShieldCheck, 
  TrendingUp, 
  Terminal, 
  GitBranch, 
  CheckCircle2, 
  Clock, 
  Sparkles,
  Code2,
  ExternalLink,
  ChevronRight,
  Filter
} from 'lucide-react';

interface DocsWhitepaperViewProps {
  whitepaper: {
    title: string;
    version: string;
    sections: Record<string, any>;
  };
  searchQuery?: string;
}

export const DocsWhitepaperView: React.FC<DocsWhitepaperViewProps> = ({
  whitepaper,
  searchQuery = ''
}) => {
  const [activeSection, setActiveSection] = useState('overview');
  const [featureCategory, setFeatureCategory] = useState<string>('all');
  const sections = whitepaper.sections || {};

  const tocItems = [
    { id: 'overview', title: 'B. Product Overview' },
    { id: 'feature_matrix', title: 'C. Feature Matrix' },
    { id: 'architecture_diagram', title: 'D. Architecture Diagram' },
    { id: 'data_flow_diagram', title: 'E. Data Flow Diagram' },
    { id: 'tech_stack', title: 'F. Technology Stack' },
    { id: 'api_documentation', title: 'G. API Documentation & MCP' },
    { id: 'data_layer', title: 'H. Data Layer & Sovereign Storage' },
    { id: 'ai_layer', title: 'I. AI Layer & GraphRAG' },
    { id: 'roadmap', title: 'J. Product Roadmap' },
    { id: 'performance', title: 'K. Performance & Scalability' },
    { id: 'security', title: 'L. Security & RBAC' },
    { id: 'analytics', title: 'M. Live Analytics & KPIs' },
    { id: 'changelog', title: 'O. Changelog & Version History' },
  ];

  const scrollToSection = (id: string) => {
    setActiveSection(id);
    const el = document.getElementById(id);
    if (el) {
      el.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
  };

  return (
    <div className="w-full max-w-7xl mx-auto px-4 py-8 animate-in fade-in duration-200">
      
      {/* Title & Tagline */}
      <div className="text-center space-y-3 max-w-3xl mx-auto mb-10">
        <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full text-xs font-bold border bg-blue-50 dark:bg-blue-500/10 border-blue-200 dark:border-[#7c6fd6]/30 text-[#7c6fd6] dark:text-[#a59bf3] shadow-xs"
        >
          <FileText className="w-3.5 h-3.5" />
          <span>Engineering Systems Whitepaper</span>
        </div>

        <h1 className="text-3xl sm:text-4xl font-extrabold tracking-tight text-[var(--foreground)]">
          {whitepaper.title || "LORE Enterprise Technical Whitepaper"}
        </h1>

        <p className="text-xs sm:text-sm text-[var(--muted-foreground)] font-mono">
          Specification Version: {whitepaper.version || "2.0.0-enterprise"} • Build Target: Production Sovereign
        </p>
      </div>

      <div className="flex flex-col lg:flex-row gap-8 items-start">
        
        {/* Sticky Sidebar Table of Contents */}
        <aside className="w-full lg:w-64 shrink-0 lg:sticky lg:top-24 space-y-2 p-4 rounded-2xl border bg-white dark:bg-slate-900/60 border-[var(--border)] backdrop-blur-md shadow-sm"
        >
          <div className="text-[11px] font-bold text-[var(--muted-foreground)] uppercase tracking-wider px-2 pb-2 border-b border-[var(--border)]">
            Table of Contents
          </div>
          <nav className="space-y-1 max-h-[70vh] overflow-y-auto pr-1">
            {tocItems.map(item => (
              <button
                key={item.id}
                onClick={() => scrollToSection(item.id)}
                className={`w-full text-left px-2.5 py-1.5 rounded-lg text-xs font-semibold transition-all flex items-center justify-between group ${
                  activeSection === item.id
                    ? 'bg-blue-50 dark:bg-[#7c6fd6]/20 text-blue-700 dark:text-[#a59bf3] border border-blue-200 dark:border-[#7c6fd6]/30'
                    : 'text-[var(--muted-foreground)] hover:text-slate-900 dark:hover:text-white hover:bg-slate-100 dark:hover:bg-slate-800/60'
                }`}
              >
                <span className="truncate">{item.title}</span>
                <ChevronRight className={`w-3 h-3 transition-transform ${activeSection === item.id ? 'translate-x-0.5 text-[#7c6fd6] dark:text-[#a59bf3]' : 'opacity-0 group-hover:opacity-100'}`} />
              </button>
            ))}
          </nav>
        </aside>

        {/* Main Content Sections */}
        <main className="flex-1 space-y-14 min-w-0">
          
          {/* Section B: Product Overview */}
          <section id="overview" className="scroll-mt-24 space-y-4 p-8 rounded-3xl border bg-[var(--card)] border-[var(--border)] shadow-[var(--lore-card-shadow)] shadow-sm dark:shadow-xl"
          >
            <div className="flex items-center gap-2 text-xs font-bold text-[#7c6fd6] dark:text-[#a59bf3] uppercase tracking-wider">
              <ShieldCheck className="w-4 h-4" />
              <span>Section B</span>
            </div>
            <h2 className="text-2xl font-extrabold text-[var(--foreground)]">
              {sections.overview?.title || "B. Product Overview & System Guarantees"}
            </h2>
            <div className="text-sm text-slate-600 dark:text-slate-300 leading-relaxed space-y-3 font-normal">
              <p>
                {sections.overview?.content || "LORE (Logic, Observability, Reasoning, and Evidence) is a deterministic governance and knowledge operating system engineered for enterprise compliance workloads and autonomous AI agents."}
              </p>
            </div>

            {/* Invariants Grid */}
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 pt-4">
              <div className="p-4 rounded-xl border bg-slate-50 dark:bg-slate-800/40 border-[var(--border)]/60">
                <h4 className="font-bold text-xs text-[#7c6fd6] dark:text-[#a59bf3] mb-1">lore.result/2 Protocol</h4>
                <p className="text-xs text-[var(--muted-foreground)]">
                  Every decision produces a strictly validated JSON envelope with mandatory directive and cited locators.
                </p>
              </div>
              <div className="p-4 rounded-xl border bg-slate-50 dark:bg-slate-800/40 border-[var(--border)]/60">
                <h4 className="font-bold text-xs text-emerald-600 dark:text-emerald-400 mb-1">Zero Stochastic Hallucinations</h4>
                <p className="text-xs text-[var(--muted-foreground)]">
                  Answers unsupported by mathematical passage sufficiency are rejected before prompt synthesis.
                </p>
              </div>
            </div>
          </section>

          {/* Section C: Live Feature Matrix */}
          <section id="feature_matrix" className="scroll-mt-24 space-y-4 p-8 rounded-3xl border bg-[var(--card)] border-[var(--border)] shadow-[var(--lore-card-shadow)] shadow-sm dark:shadow-xl"
          >
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2 text-xs font-bold text-[#7c6fd6] dark:text-[#a59bf3] uppercase tracking-wider">
                <Layers className="w-4 h-4" />
                <span>Section C</span>
              </div>

              {/* Category Filter Pills */}
              <div className="flex items-center gap-1.5 text-xs">
                {['all', 'Governance', 'Pipeline', 'Cryptography', 'Storage'].map(cat => (
                  <button
                    key={cat}
                    onClick={() => setFeatureCategory(cat)}
                    className={`px-2.5 py-1 rounded-lg font-semibold transition-colors ${
                      featureCategory === cat
                        ? 'bg-[#7c6fd6] text-white'
                        : 'bg-[var(--muted)] text-[var(--muted-foreground)] hover:text-slate-900 dark:hover:text-white hover:bg-slate-200 dark:hover:bg-slate-700'
                    }`}
                  >
                    {cat}
                  </button>
                ))}
              </div>
            </div>

            <h2 className="text-2xl font-extrabold text-[var(--foreground)]">
              {sections.feature_matrix?.title || "C. Live Feature Matrix"}
            </h2>

            <div className="overflow-x-auto rounded-2xl border border-[var(--border)]">
              <table className="w-full text-left text-xs">
                <thead className="bg-[var(--muted)]/70 text-[var(--foreground)] font-bold uppercase tracking-wider text-[10px]">
                  <tr>
                    <th className="p-3.5">Feature Name</th>
                    <th className="p-3.5">Category</th>
                    <th className="p-3.5">Status</th>
                    <th className="p-3.5">Capability Details</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-200 dark:divide-slate-800 bg-white dark:bg-slate-900/40">
                  {(sections.feature_matrix?.features || [])
                    .filter((f: any) => featureCategory === 'all' || f.category === featureCategory)
                    .map((feat: any, idx: number) => (
                      <tr key={idx} className="hover:bg-slate-50 dark:hover:bg-slate-800/30 transition-colors">
                        <td className="p-3.5 font-bold text-[var(--foreground)]">
                          {feat.name}
                        </td>
                        <td className="p-3.5">
                          <span className="px-2 py-0.5 rounded text-[10px] font-mono font-semibold bg-[var(--muted)] text-[var(--foreground)] border border-[var(--border)]">
                            {feat.category}
                          </span>
                        </td>
                        <td className="p-3.5">
                          <span className={`inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-[10px] font-bold ${
                            feat.status.includes('Live') 
                              ? 'bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border border-emerald-500/30'
                              : 'bg-amber-500/10 text-amber-600 dark:text-amber-400 border border-amber-500/30'
                          }`}>
                            <span className="w-1.5 h-1.5 rounded-full bg-current" />
                            <span>{feat.status}</span>
                          </span>
                        </td>
                        <td className="p-3.5 text-[var(--muted-foreground)]">
                          {feat.description}
                        </td>
                      </tr>
                    ))}
                </tbody>
              </table>
            </div>
          </section>

          {/* Section D: Architecture Diagram */}
          <section id="architecture_diagram" className="scroll-mt-24 space-y-4 p-8 rounded-3xl border bg-[var(--card)] border-[var(--border)] shadow-[var(--lore-card-shadow)] shadow-sm dark:shadow-xl"
          >
            <div className="flex items-center gap-2 text-xs font-bold text-[#7c6fd6] dark:text-[#a59bf3] uppercase tracking-wider">
              <Cpu className="w-4 h-4" />
              <span>Section D</span>
            </div>
            <h2 className="text-2xl font-extrabold text-[var(--foreground)]">
              {sections.architecture_diagram?.title || "D. Architecture Diagram"}
            </h2>

            {/* Architecture SVG Flowchart Display */}
            <div className="p-6 rounded-2xl border bg-slate-950 font-mono text-xs overflow-x-auto space-y-6 border-slate-800"
            >
              <div className="flex items-center justify-between text-[11px] text-slate-400 border-b border-slate-800 pb-2">
                <span>Architecture Topology (Mermaid DSL)</span>
                <span className="text-emerald-400">Interactive Runtime Component Map</span>
              </div>
              <pre className="text-blue-300 text-[11px] leading-relaxed">
                {sections.architecture_diagram?.mermaid || "UI -> API -> Governance -> TripleStore"}
              </pre>
            </div>
          </section>

          {/* Section E: Data Flow Diagram */}
          <section id="data_flow_diagram" className="scroll-mt-24 space-y-4 p-8 rounded-3xl border bg-[var(--card)] border-[var(--border)] shadow-[var(--lore-card-shadow)] shadow-sm dark:shadow-xl"
          >
            <div className="flex items-center gap-2 text-xs font-bold text-[#7c6fd6] dark:text-[#a59bf3] uppercase tracking-wider">
              <GitBranch className="w-4 h-4" />
              <span>Section E</span>
            </div>
            <h2 className="text-2xl font-extrabold text-[var(--foreground)]">
              {sections.data_flow_diagram?.title || "E. Data Flow & Settlement Sequence"}
            </h2>

            <div className="p-6 rounded-2xl border bg-slate-950 font-mono text-xs overflow-x-auto space-y-6 border-slate-800"
            >
              <div className="flex items-center justify-between text-[11px] text-slate-400 border-b border-slate-800 pb-2">
                <span>Sequence Execution Flow (Mermaid Sequence Diagram)</span>
                <span className="text-[#a59bf3]">S1-S6 Settlement Gate → 8-Layer Gate</span>
              </div>
              <pre className="text-emerald-300 text-[11px] leading-relaxed">
                {sections.data_flow_diagram?.mermaid || "User -> Ingestion -> Indexing -> Query -> Verification"}
              </pre>
            </div>
          </section>

          {/* Section F: Technology Stack */}
          <section id="tech_stack" className="scroll-mt-24 space-y-4 p-8 rounded-3xl border bg-[var(--card)] border-[var(--border)] shadow-[var(--lore-card-shadow)] shadow-sm dark:shadow-xl"
          >
            <div className="flex items-center gap-2 text-xs font-bold text-[#7c6fd6] dark:text-[#a59bf3] uppercase tracking-wider">
              <Terminal className="w-4 h-4" />
              <span>Section F</span>
            </div>
            <h2 className="text-2xl font-extrabold text-[var(--foreground)]">
              {sections.tech_stack?.title || "F. Technology Stack"}
            </h2>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {(sections.tech_stack?.layers || []).map((layer: any, idx: number) => (
                <div key={idx} className="p-4 rounded-xl border bg-slate-50 dark:bg-slate-850/50 border-[var(--border)]/60 space-y-1">
                  <h4 className="font-bold text-xs text-[#7c6fd6] dark:text-[#a59bf3] uppercase tracking-wider">{layer.name}</h4>
                  <p className="text-xs text-slate-800 dark:text-slate-100 font-mono font-semibold">{layer.stack}</p>
                </div>
              ))}
            </div>
          </section>

          {/* Section G: API Documentation & MCP */}
          <section id="api_documentation" className="scroll-mt-24 space-y-4 p-8 rounded-3xl border bg-[var(--card)] border-[var(--border)] shadow-[var(--lore-card-shadow)] shadow-sm dark:shadow-xl"
          >
            <div className="flex items-center gap-2 text-xs font-bold text-[#7c6fd6] dark:text-[#a59bf3] uppercase tracking-wider">
              <Code2 className="w-4 h-4" />
              <span>Section G</span>
            </div>
            <h2 className="text-2xl font-extrabold text-[var(--foreground)]">
              {sections.api_documentation?.title || "G. API Documentation & MCP 41 Tools"}
            </h2>
            <div className="text-sm text-[var(--foreground)] leading-relaxed font-mono whitespace-pre-wrap bg-[var(--background)]/80 p-5 rounded-2xl border border-[var(--border)] shadow-inner"
            >
              {sections.api_documentation?.content}
            </div>
          </section>

          {/* Section H & I: Data Layer & AI Layer */}
          <section id="data_layer" className="scroll-mt-24 space-y-4 p-8 rounded-3xl border bg-[var(--card)] border-[var(--border)] shadow-[var(--lore-card-shadow)] shadow-sm dark:shadow-xl"
          >
            <div className="flex items-center gap-2 text-xs font-bold text-[#7c6fd6] dark:text-[#a59bf3] uppercase tracking-wider">
              <Database className="w-4 h-4" />
              <span>Section H & I</span>
            </div>
            <h2 className="text-2xl font-extrabold text-[var(--foreground)]">
              {sections.data_layer?.title || "H. Data Layer & Sovereign Storage"}
            </h2>
            <p className="text-sm text-slate-600 dark:text-slate-300 leading-relaxed font-normal">
              {sections.data_layer?.content}
            </p>

            <h3 className="text-xl font-bold text-[var(--foreground)] pt-4">
              {sections.ai_layer?.title || "I. AI Layer & Deterministic GraphRAG"}
            </h3>
            <div className="text-sm text-slate-600 dark:text-slate-300 leading-relaxed whitespace-pre-wrap font-normal">
              {sections.ai_layer?.content}
            </div>
          </section>

          {/* Section J: Product Roadmap */}
          <section id="roadmap" className="scroll-mt-24 space-y-4 p-8 rounded-3xl border bg-[var(--card)] border-[var(--border)] shadow-[var(--lore-card-shadow)] shadow-sm dark:shadow-xl"
          >
            <div className="flex items-center gap-2 text-xs font-bold text-[#7c6fd6] dark:text-[#a59bf3] uppercase tracking-wider">
              <Clock className="w-4 h-4" />
              <span>Section J</span>
            </div>
            <h2 className="text-2xl font-extrabold text-[var(--foreground)]">
              {sections.roadmap?.title || "J. Product Roadmap"}
            </h2>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              {(sections.roadmap?.milestones || []).map((m: any, idx: number) => (
                <div key={idx} className="p-5 rounded-2xl border bg-slate-50 dark:bg-slate-800/30 border-[var(--border)]/60 space-y-2">
                  <div className="flex items-center justify-between">
                    <span className="px-2.5 py-0.5 rounded text-[10px] font-mono font-bold bg-blue-50 dark:bg-blue-500/10 text-[#7c6fd6] dark:text-[#a59bf3] border border-blue-200 dark:border-[#7c6fd6]/30">
                      {m.quarter}
                    </span>
                    <span className="text-[10px] font-bold text-emerald-600 dark:text-emerald-400">
                      {m.status}
                    </span>
                  </div>
                  <h4 className="font-bold text-sm text-[var(--foreground)]">{m.title}</h4>
                  <p className="text-xs text-[var(--muted-foreground)]">{m.details}</p>
                </div>
              ))}
            </div>
          </section>

          {/* Section K & L: Performance & Security */}
          <section id="performance" className="scroll-mt-24 space-y-4 p-8 rounded-3xl border bg-[var(--card)] border-[var(--border)] shadow-[var(--lore-card-shadow)] shadow-sm dark:shadow-xl"
          >
            <div className="flex items-center gap-2 text-xs font-bold text-[#7c6fd6] dark:text-[#a59bf3] uppercase tracking-wider">
              <TrendingUp className="w-4 h-4" />
              <span>Section K & L</span>
            </div>
            <h2 className="text-2xl font-extrabold text-[var(--foreground)]">
              {sections.performance?.title || "K. Performance & Scalability SLAs"}
            </h2>

            <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
              {(sections.performance?.metrics || []).map((mt: any, idx: number) => (
                <div key={idx} className="p-4 rounded-xl border bg-slate-50 dark:bg-slate-800/40 border-[var(--border)]/60 space-y-1">
                  <span className="text-[10px] uppercase font-bold text-[var(--muted-foreground)]">{mt.metric}</span>
                  <div className="text-lg font-bold text-emerald-600 dark:text-emerald-400">{mt.achieved}</div>
                  <span className="text-[10px] text-slate-500 font-mono">Target: {mt.target}</span>
                </div>
              ))}
            </div>

            <h3 className="text-xl font-bold text-[var(--foreground)] pt-6">
              {sections.security?.title || "L. Security, RBAC & ABAC"}
            </h3>
            <p className="text-sm text-slate-600 dark:text-slate-300 leading-relaxed whitespace-pre-wrap font-normal">
              {sections.security?.content}
            </p>
          </section>

          {/* Section O: Changelog */}
          <section id="changelog" className="scroll-mt-24 space-y-4 p-8 rounded-3xl border bg-[var(--card)] border-[var(--border)] shadow-[var(--lore-card-shadow)] shadow-sm dark:shadow-xl"
          >
            <div className="flex items-center gap-2 text-xs font-bold text-[#7c6fd6] dark:text-[#a59bf3] uppercase tracking-wider">
              <Clock className="w-4 h-4" />
              <span>Section O</span>
            </div>
            <h2 className="text-2xl font-extrabold text-[var(--foreground)]">
              {sections.changelog?.title || "O. Changelog & Semantic Version History"}
            </h2>

            <div className="space-y-6">
              {(sections.changelog?.releases || []).map((rel: any, idx: number) => (
                <div key={idx} className="border-l-2 border-[#7c6fd6] pl-4 space-y-2">
                  <div className="flex items-center gap-2">
                    <span className="font-extrabold text-sm text-[var(--foreground)]">{rel.version}</span>
                    <span className="text-xs font-mono text-[var(--muted-foreground)]">({rel.date})</span>
                  </div>
                  <ul className="space-y-1 text-xs text-[var(--muted-foreground)]">
                    {rel.highlights.map((h: string, hIdx: number) => (
                      <li key={hIdx} className="flex items-start gap-2">
                        <span className="text-[#7c6fd6]">•</span>
                        <span>{h}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              ))}
            </div>
          </section>

        </main>
      </div>

    </div>
  );
};
