'use client';

import React, { useState, useEffect, Suspense } from 'react';
import { useSearchParams } from 'next/navigation';
import { 
  api, 
  DocsManifestResponse, 
  DocsConfig 
} from '@/lib/api';
import { getStandaloneDocsManifest } from '@/data/docsData';
import { DocsHeader, DocsMode } from '@/components/docs/DocsHeader';
import { DocsPitchDeckView } from '@/components/docs/DocsPitchDeckView';
import { DocsWhitepaperView } from '@/components/docs/DocsWhitepaperView';
import { DocsTeamSection } from '@/components/docs/DocsTeamSection';
import { DocsLiveOpsView } from '@/components/docs/DocsLiveOpsView';
import { DocsLockedView } from '@/components/docs/DocsLockedView';
import { DocsAdminModal } from '@/components/docs/DocsAdminModal';
import { RotateCw, ShieldAlert, Sparkles } from 'lucide-react';

function DocsPageContent() {
  const searchParams = useSearchParams();
  const initialMode = (searchParams.get('mode') as DocsMode) || 'pitch_deck';
  const urlPasskey = searchParams.get('passkey') || '';
  const urlAdminKey = searchParams.get('admin_key') || '';

  const [mode, setMode] = useState<DocsMode>(initialMode);
  const [searchQuery, setSearchQuery] = useState('');
  const [manifest, setManifest] = useState<DocsManifestResponse | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [unlockError, setUnlockError] = useState<string | null>(null);
  const [passkey, setPasskey] = useState<string>(urlPasskey);
  const [isAdminModalOpen, setIsAdminModalOpen] = useState(false);
  const [isTelemetryRefreshing, setIsTelemetryRefreshing] = useState(false);

  // Load passkey from sessionStorage if previously entered
  useEffect(() => {
    if (typeof window !== 'undefined') {
      const stored = sessionStorage.getItem('lore_judge_passkey');
      if (stored && !passkey) {
        setPasskey(stored);
      }
    }
  }, []);

  const loadManifest = async (customPasskey?: string) => {
    setIsLoading(true);
    setError(null);
    setUnlockError(null);
    const activePasskey = customPasskey !== undefined ? customPasskey : passkey;

    try {
      const res = await api.getDocsManifest(activePasskey || undefined, urlAdminKey || undefined);
      setManifest(res);
      if (!res.is_open && customPasskey) {
        setUnlockError('Invalid passkey. Default judge passkey is: LORE2026');
      } else if (res.is_open && customPasskey) {
        if (typeof window !== 'undefined') {
          sessionStorage.setItem('lore_judge_passkey', customPasskey);
        }
        setPasskey(customPasskey);
      }
    } catch (err: any) {
      console.warn("Backend /docs unavailable. Seamlessly activating standalone offline manifest:", err);
      // 100% Zero-Backend Resilience: Fallback to bundled static manifest
      const fallbackRes = getStandaloneDocsManifest(activePasskey || undefined, urlAdminKey || undefined);
      setManifest(fallbackRes as any);
      if (!fallbackRes.is_open && customPasskey) {
        setUnlockError('Invalid passkey. Default judge passkey is: LORE2026');
      } else if (fallbackRes.is_open && customPasskey) {
        if (typeof window !== 'undefined') {
          sessionStorage.setItem('lore_judge_passkey', customPasskey);
        }
        setPasskey(customPasskey);
      }
    } finally {
      setIsLoading(false);
    }
  };

  const handleRefreshTelemetry = async () => {
    setIsTelemetryRefreshing(true);
    try {
      const tel = await api.getDocsTelemetry();
      if (manifest) {
        setManifest({
          ...manifest,
          live_telemetry: tel
        });
      }
    } catch (err) {
      console.warn("Could not refresh live telemetry:", err);
    } finally {
      setIsTelemetryRefreshing(false);
    }
  };

  useEffect(() => {
    loadManifest();
  }, [passkey]);

  if (isLoading) {
    return (
      <div className="min-h-screen bg-slate-50 dark:bg-slate-950 flex flex-col items-center justify-center space-y-4 text-slate-600 dark:text-slate-400">
        <RotateCw className="w-8 h-8 text-blue-500 animate-spin" />
        <p className="text-xs font-mono">Loading LORE Enterprise /docs module...</p>
      </div>
    );
  }

  if (error || !manifest) {
    return (
      <div className="min-h-screen bg-slate-50 dark:bg-slate-950 flex flex-col items-center justify-center p-4 text-center">
        <div className="p-6 rounded-3xl border border-red-500/30 bg-red-500/10 max-w-md space-y-3">
          <ShieldAlert className="w-10 h-10 text-red-500 mx-auto" />
          <h2 className="text-lg font-bold text-slate-900 dark:text-white">Documentation Service Unavailable</h2>
          <p className="text-xs text-slate-600 dark:text-slate-400">{error || 'Could not retrieve documentation manifest.'}</p>
          <button
            onClick={() => loadManifest()}
            className="px-4 py-2 rounded-xl bg-blue-600 hover:bg-blue-500 text-white text-xs font-bold transition-all shadow-md"
          >
            Retry Connection
          </button>
        </div>
      </div>
    );
  }

  // If Access is Locked (Outside Schedule & Not Admin)
  if (!manifest.is_open) {
    return (
      <div className="min-h-screen bg-slate-50 text-slate-900 dark:bg-slate-950 dark:text-slate-100 flex flex-col justify-between transition-colors duration-200">
        <DocsLockedView
          config={manifest.config}
          message={manifest.message}
          scheduleWindow={manifest.schedule_window}
          onUnlockWithPasskey={(enteredPasskey) => loadManifest(enteredPasskey)}
          onOpenAdmin={() => setIsAdminModalOpen(true)}
          unlockError={unlockError}
        />

        {/* Admin Controls Modal */}
        <DocsAdminModal
          isOpen={isAdminModalOpen}
          onClose={() => setIsAdminModalOpen(false)}
          config={manifest.config}
          teamData={manifest.team}
          onSuccess={() => loadManifest()}
        />

        <footer className="py-6 border-t border-slate-200 dark:border-slate-900 text-center text-xs text-slate-500 dark:text-slate-600 font-mono">
          LORE Enterprise OS • Cryptographic Truth Engine • v2.0.0
        </footer>
      </div>
    );
  }

  // When Active & Unlocked: Full Documentation Suite
  return (
    <div className="min-h-screen bg-slate-50 text-slate-900 dark:bg-slate-950 dark:text-slate-100 flex flex-col selection:bg-blue-500 selection:text-white transition-colors duration-200">
      
      {/* Universal Sticky Header */}
      <DocsHeader
        mode={mode}
        onModeChange={(newMode) => {
          setMode(newMode);
          if (typeof window !== 'undefined') {
            const url = new URL(window.location.href);
            url.searchParams.set('mode', newMode);
            window.history.replaceState({}, '', url.toString());
          }
        }}
        searchQuery={searchQuery}
        onSearchChange={setSearchQuery}
        config={manifest.config}
        isAdmin={Boolean(manifest.is_admin)}
        onOpenAdmin={() => setIsAdminModalOpen(true)}
      />

      {/* Main Content Area by Selected Mode */}
      <main className="flex-1 pb-16">
        {mode === 'pitch_deck' && manifest.pitch_deck && (
          <DocsPitchDeckView
            slides={manifest.pitch_deck.slides || []}
            title={manifest.pitch_deck.title}
            tagline={manifest.pitch_deck.tagline}
            searchQuery={searchQuery}
          />
        )}

        {mode === 'whitepaper' && manifest.whitepaper && (
          <DocsWhitepaperView
            whitepaper={manifest.whitepaper}
            searchQuery={searchQuery}
          />
        )}

        {mode === 'live_ops' && (
          <DocsLiveOpsView
            telemetry={manifest.live_telemetry}
            onRefresh={handleRefreshTelemetry}
            isLoading={isTelemetryRefreshing}
          />
        )}

        {mode === 'team' && manifest.team && (
          <DocsTeamSection
            teamName={manifest.team.team_name}
            charter={manifest.team.charter}
            members={manifest.team.members || []}
            isAdmin={Boolean(manifest.is_admin)}
            onOpenAdmin={() => setIsAdminModalOpen(true)}
          />
        )}
      </main>

      {/* Admin Settings & Scheduling Drawer */}
      <DocsAdminModal
        isOpen={isAdminModalOpen}
        onClose={() => setIsAdminModalOpen(false)}
        config={manifest.config}
        teamData={manifest.team}
        onSuccess={() => loadManifest()}
      />

      {/* Global Footer */}
      <footer className="border-t border-slate-200 dark:border-slate-900 bg-white dark:bg-slate-950/80 py-8 px-4 text-xs text-slate-500 dark:text-slate-400 font-mono">
        <div className="max-w-7xl mx-auto flex flex-col sm:flex-row items-center justify-between gap-4">
          <div className="flex items-center gap-2">
            <span className="font-bold text-slate-800 dark:text-slate-200">LORE Enterprise</span>
            <span>•</span>
            <span>Deterministic AI Governance</span>
            <span>•</span>
            <span className="text-emerald-600 dark:text-emerald-400 font-semibold">100% Zero-LLM Core</span>
          </div>

          <div className="flex items-center gap-4 text-[11px]">
            <span>Model Context Protocol (Port 8001)</span>
            <span>•</span>
            <a href="/" className="text-blue-600 dark:text-blue-400 hover:underline">
              Enter Workspace
            </a>
            <span>•</span>
            <button
              onClick={() => setIsAdminModalOpen(true)}
              className="text-amber-600 dark:text-amber-400 hover:underline font-semibold"
            >
              Admin Controls
            </button>
          </div>
        </div>
      </footer>

    </div>
  );
}

export default function DocsPage() {
  return (
    <Suspense fallback={
      <div className="min-h-screen bg-slate-50 dark:bg-slate-950 flex flex-col items-center justify-center text-slate-500 dark:text-slate-400">
        <RotateCw className="w-8 h-8 text-blue-500 animate-spin mb-2" />
        <span className="text-xs font-mono">Initializing /docs...</span>
      </div>
    }>
      <DocsPageContent />
    </Suspense>
  );
}
