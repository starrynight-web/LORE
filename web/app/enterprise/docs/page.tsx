'use client';

import React, { useState, useEffect, Suspense } from 'react';
import { useSearchParams } from 'next/navigation';
import { DocsManifestResponse, DocsConfig } from '@/lib/docs-types';
import { getStandaloneDocsManifest } from '@/data/docsData';
import { SiteHeader } from '@/components/site-header';
import { SiteFooter } from '@/components/site-footer';
import { DocsHeader, DocsMode } from '@/components/docs/DocsHeader';
import { DocsPitchDeckView } from '@/components/docs/DocsPitchDeckView';
import { DocsWhitepaperView } from '@/components/docs/DocsWhitepaperView';
import { DocsTeamSection } from '@/components/docs/DocsTeamSection';
import { DocsLiveOpsView } from '@/components/docs/DocsLiveOpsView';
import { DocsLoginGate } from '@/components/docs/DocsLoginGate';
import { DocsAdminModal } from '@/components/docs/DocsAdminModal';
import { RotateCw, ShieldAlert } from 'lucide-react';

const REQUIRED_ID = 'lore@unleft.space';
const REQUIRED_PASS = 'LORE2026';

function DocsContent() {
  const searchParams = useSearchParams();
  const initialMode = (searchParams.get('mode') as DocsMode) || 'pitch_deck';
  
  // URL credentials support: ?id=lore@unleft.space&pass=LORE2026 or ?passkey=LORE2026
  const urlId = searchParams.get('id') || searchParams.get('email') || '';
  const urlPass = searchParams.get('pass') || searchParams.get('password') || searchParams.get('passkey') || '';
  const urlAdminKey = searchParams.get('admin_key') || '';

  const [mode, setMode] = useState<DocsMode>(initialMode);
  const [searchQuery, setSearchQuery] = useState('');
  const [manifest, setManifest] = useState<DocsManifestResponse | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [isAdminModalOpen, setIsAdminModalOpen] = useState(false);
  const [isTelemetryRefreshing, setIsTelemetryRefreshing] = useState(false);

  // Authentication State
  const [isAuthenticated, setIsAuthenticated] = useState<boolean>(false);
  const [currentUser, setCurrentUser] = useState<string | null>(null);

  // Check stored auth or URL query params on mount
  useEffect(() => {
    let authenticated = false;

    // 1. Check URL parameters
    if (urlPass === REQUIRED_PASS && (!urlId || urlId.toLowerCase() === REQUIRED_ID.toLowerCase())) {
      authenticated = true;
      const user = urlId || REQUIRED_ID;
      setIsAuthenticated(true);
      setCurrentUser(user);
      if (typeof window !== 'undefined') {
        sessionStorage.setItem('lore_enterprise_auth', JSON.stringify({ id: user, timestamp: Date.now() }));
      }
    }

    // 2. Check session storage if not already authenticated via URL
    if (!authenticated && typeof window !== 'undefined') {
      try {
        const stored = sessionStorage.getItem('lore_enterprise_auth');
        if (stored) {
          const parsed = JSON.parse(stored);
          if (parsed?.id && parsed.id.toLowerCase() === REQUIRED_ID.toLowerCase()) {
            setIsAuthenticated(true);
            setCurrentUser(parsed.id);
            authenticated = true;
          }
        }
      } catch (e) {
        console.warn('Failed to parse auth token:', e);
      }
    }

    // Load manifest
    try {
      const res = getStandaloneDocsManifest(REQUIRED_PASS, urlAdminKey || undefined);
      setManifest(res);
    } catch (err: any) {
      console.error('Failed to load docs manifest:', err);
      setError('Could not load enterprise documentation manifest.');
    } finally {
      setIsLoading(false);
    }
  }, [urlId, urlPass, urlAdminKey]);

  const handleLogin = (enteredId: string, enteredPass: string): boolean => {
    const idClean = enteredId.trim().toLowerCase();
    const passClean = enteredPass.trim();

    if (idClean === REQUIRED_ID.toLowerCase() && passClean === REQUIRED_PASS) {
      setIsAuthenticated(true);
      setCurrentUser(enteredId.trim());
      if (typeof window !== 'undefined') {
        sessionStorage.setItem('lore_enterprise_auth', JSON.stringify({ id: enteredId.trim(), timestamp: Date.now() }));
      }
      return true;
    }
    return false;
  };

  const handleSignOut = () => {
    setIsAuthenticated(false);
    setCurrentUser(null);
    if (typeof window !== 'undefined') {
      sessionStorage.removeItem('lore_enterprise_auth');
      // Also clean up query params without reloading
      const url = new URL(window.location.href);
      url.searchParams.delete('id');
      url.searchParams.delete('pass');
      url.searchParams.delete('password');
      url.searchParams.delete('passkey');
      window.history.replaceState({}, '', url.toString());
    }
  };

  const handleRefreshTelemetry = () => {
    setIsTelemetryRefreshing(true);
    setTimeout(() => {
      if (manifest) {
        const fresh = getStandaloneDocsManifest(REQUIRED_PASS, urlAdminKey);
        setManifest({
          ...manifest,
          live_telemetry: fresh.live_telemetry
        });
      }
      setIsTelemetryRefreshing(false);
    }, 400);
  };

  if (isLoading) {
    return (
      <div className="min-h-screen bg-[var(--background)] flex flex-col items-center justify-center space-y-4 text-[var(--muted-foreground)]">
        <RotateCw className="w-8 h-8 text-[#7c6fd6] animate-spin" />
        <p className="text-xs font-mono">Verifying enterprise security session...</p>
      </div>
    );
  }

  if (error || !manifest) {
    return (
      <div className="min-h-screen bg-[var(--background)] flex flex-col items-center justify-center p-4 text-center">
        <div className="p-6 rounded-3xl border border-red-500/30 bg-red-500/10 max-w-md space-y-3">
          <ShieldAlert className="w-10 h-10 text-red-500 mx-auto" />
          <h2 className="text-lg font-bold text-[var(--foreground)]">Documentation Module Unavailable</h2>
          <p className="text-xs text-[var(--muted-foreground)]">{error || 'Could not retrieve documentation manifest.'}</p>
          <button
            onClick={() => window.location.reload()}
            className="px-4 py-2 rounded-xl bg-[#7c6fd6] hover:bg-[#5f52c4] text-white text-xs font-bold transition-all shadow-md"
          >
            Retry Connection
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen flex flex-col bg-[var(--background)] text-[var(--foreground)] selection:bg-[#7c6fd6] selection:text-white transition-colors duration-200">
      {/* Site Header */}
      <SiteHeader />

      {/* Access Gate: If not authenticated, require ID: lore@unleft.space & Pass: LORE2026 */}
      {!isAuthenticated ? (
        <main className="flex-1 flex flex-col justify-center">
          <DocsLoginGate onLogin={handleLogin} />
        </main>
      ) : (
        /* When Authenticated: Full Enterprise Documentation Suite */
        <div className="flex-1 flex flex-col">
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
            currentUser={currentUser || REQUIRED_ID}
            onSignOut={handleSignOut}
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
            onSuccess={() => {
              const fresh = getStandaloneDocsManifest(REQUIRED_PASS, urlAdminKey);
              setManifest(fresh);
            }}
          />
        </div>
      )}

      {/* Site Footer */}
      <SiteFooter />
    </div>
  );
}

export default function EnterpriseDocsPage() {
  return (
    <Suspense
      fallback={
        <div className="min-h-screen bg-[var(--background)] flex flex-col items-center justify-center text-[var(--muted-foreground)]">
          <RotateCw className="w-8 h-8 text-[#7c6fd6] animate-spin mb-2" />
          <span className="text-xs font-mono">Initializing /enterprise/docs...</span>
        </div>
      }
    >
      <DocsContent />
    </Suspense>
  );
}
