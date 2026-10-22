'use client';

import React, { useState, useEffect } from 'react';
import { Sidebar } from '@/components/Sidebar';
import { Header } from '@/components/Header';
import { OverviewView } from '@/components/OverviewView';
import { DocumentList } from '@/components/DocumentList';
import { IngestionActivityView } from '@/components/IngestionActivityView';
import { GovernedRAGView } from '@/components/GovernedRAGView';
import { ReviewQueueView } from '@/components/ReviewQueueView';
import { AuditView } from '@/components/AuditView';
import { UploadModal } from '@/components/UploadModal';
import { DocumentDetailModal } from '@/components/DocumentDetailModal';
import { RealtimeOCRStudio } from '@/components/RealtimeOCRStudio';
import { AuthModal } from '@/components/AuthModal';
import { OrganizationSettingsView } from '@/components/OrganizationSettingsView';
import { 
  api, 
  Workspace, 
  Organization, 
  Collection, 
  SourceDocument, 
  IngestionJob, 
  AuditEvent,
  User as UserType
} from '@/lib/api';

export default function Home() {
  const [activeTab, setActiveTab] = useState('overview');
  const [currentUser, setCurrentUser] = useState<UserType | null>(null);
  const [isAuthenticated, setIsAuthenticated] = useState<boolean>(false);
  const [isGuestMode, setIsGuestMode] = useState<boolean>(true);
  const [isAuthModalOpen, setIsAuthModalOpen] = useState<boolean>(false);
  const [currentOrg, setCurrentOrg] = useState<Organization | null>(null);
  const [currentWorkspace, setCurrentWorkspace] = useState<Workspace | null>(null);
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [collections, setCollections] = useState<Collection[]>([]);
  const [documents, setDocuments] = useState<SourceDocument[]>([]);
  const [jobs, setJobs] = useState<IngestionJob[]>([]);
  const [reviewDocs, setReviewDocs] = useState<SourceDocument[]>([]);
  const [auditEvents, setAuditEvents] = useState<AuditEvent[]>([]);

  const [isUploadModalOpen, setIsUploadModalOpen] = useState(false);
  const [selectedDocument, setSelectedDocument] = useState<SourceDocument | null>(null);
  const [ragScopedDocId, setRagScopedDocId] = useState<string | undefined>(undefined);
  const [isLoading, setIsLoading] = useState(true);

  // Authenticate and load initial data
  const loadWorkspaceData = async (wsId: string) => {
    try {
      const [docs, cList, jList, rList, aList] = await Promise.all([
        api.getDocuments(wsId),
        api.getCollections(wsId),
        api.getJobs(wsId),
        api.getReviewQueue(wsId),
        api.getAuditEvents(wsId),
      ]);
      setDocuments(docs);
      setCollections(cList);
      setJobs(jList);
      setReviewDocs(rList);
      setAuditEvents(aList);
    } catch (err) {
      console.error("Error loading workspace data:", err);
    }
  };

  const handleAuthSuccess = async (data: { user: UserType; organizations?: Organization[] }, isGuest: boolean = false) => {
    setIsLoading(true);
    setCurrentUser(data.user);
    setIsAuthenticated(true);
    setIsGuestMode(isGuest);
    try {
      const wsList = await api.getWorkspaces();
      setWorkspaces(wsList);

      if (wsList.length > 0) {
        const defaultWs = wsList[0];
        setCurrentWorkspace(defaultWs);
        setCurrentOrg({
          id: defaultWs.organization,
          name: defaultWs.organization_name,
          slug: defaultWs.organization_name.toLowerCase().replace(/[^a-z0-9]+/g, '-'),
          description: '',
          role: defaultWs.role
        });
        await loadWorkspaceData(defaultWs.id);
      } else {
        setCurrentWorkspace(null);
        setDocuments([]);
      }
    } catch (err) {
      console.error("Post-auth error:", err);
    } finally {
      setIsLoading(false);
    }
  };

  const handleLogout = async () => {
    await api.logout();
    setIsAuthenticated(false);
    setIsAuthModalOpen(true);
  };

  useEffect(() => {
    const checkSession = async () => {
      setIsLoading(true);
      try {
        const meData = await api.me();
        await handleAuthSuccess(meData, false);
      } catch (err) {
        // Automatic Guest Mode: Login as demo admin to enable full workspace access with zero friction
        try {
          const guestRes = await api.login('admin@northstar.demo', 'Northstar2026!');
          await handleAuthSuccess(guestRes, true);
        } catch (guestErr) {
          console.error("Guest mode auto-connect error:", guestErr);
          setIsAuthenticated(false);
          setIsAuthModalOpen(true);
        }
      } finally {
        setIsLoading(false);
      }
    };

    checkSession();
  }, []);

  // Poll for background ingestion updates if jobs are in-progress
  useEffect(() => {
    if (!currentWorkspace) return;
    const interval = setInterval(() => {
      const hasActive = jobs.some(j => j.status !== 'ready' && j.status !== 'failed');
      if (hasActive) {
        api.getJobs(currentWorkspace.id).then(setJobs).catch(() => {});
        api.getDocuments(currentWorkspace.id).then(setDocuments).catch(() => {});
      }
    }, 2500);
    return () => clearInterval(interval);
  }, [currentWorkspace, jobs]);

  const handleRefreshCurrentWorkspace = () => {
    if (currentWorkspace) {
      loadWorkspaceData(currentWorkspace.id);
    }
  };

  const handleUploadSuccess = (docId: string, jobId: string) => {
    handleRefreshCurrentWorkspace();
    setActiveTab('activity');
  };

  const activeJobsCount = jobs.filter(j => j.status !== 'ready' && j.status !== 'failed').length;

  return (
    <div 
      className="flex h-screen overflow-hidden transition-colors duration-200"
      style={{
        backgroundColor: 'var(--bg-primary)',
        color: 'var(--text-primary)',
      }}
    >
      {/* Sidebar */}
      <Sidebar
        activeTab={activeTab}
        setActiveTab={setActiveTab}
        reviewCount={reviewDocs.length}
        activeJobsCount={activeJobsCount}
      />

      {/* Main Workspace Frame */}
      <div className="flex-1 flex flex-col h-screen overflow-hidden">
        <Header
          currentUser={currentUser}
          currentOrg={currentOrg}
          currentWorkspace={currentWorkspace}
          workspaces={workspaces}
          isGuestMode={isGuestMode}
          onSelectWorkspace={(ws) => {
            setCurrentWorkspace(ws);
            loadWorkspaceData(ws.id);
          }}
          onOpenUpload={() => setIsUploadModalOpen(true)}
          onSearchClick={() => setActiveTab('rag')}
          onLogout={handleLogout}
          onOpenAuthModal={() => setIsAuthModalOpen(true)}
        />

        {/* Viewport */}
        <main 
          className="flex-1 overflow-y-auto p-6 md:p-8 transition-colors duration-200"
          style={{
            backgroundColor: 'var(--bg-primary)',
          }}
        >
          {isLoading ? (
            <div className="flex flex-col items-center justify-center h-full space-y-3">
              <div 
                className="w-8 h-8 border-2 border-t-transparent rounded-full animate-spin"
                style={{
                  borderColor: 'var(--brand-accent)',
                  borderTopColor: 'transparent',
                }}
              />
              <div className="text-xs font-semibold text-[var(--text-secondary)]">Connecting to LORE Enterprise Grid...</div>
            </div>
          ) : (
            <>
              {activeTab === 'overview' && (
                <OverviewView
                  documents={documents}
                  jobs={jobs}
                  onOpenUpload={() => setIsUploadModalOpen(true)}
                  onNavigate={setActiveTab}
                />
              )}

              {activeTab === 'ocr' && (
                <RealtimeOCRStudio
                  workspaceId={currentWorkspace?.id}
                  collections={collections}
                  onDocumentSaved={() => handleRefreshCurrentWorkspace()}
                  onNavigateToRAG={(docId) => {
                    if (docId) setRagScopedDocId(docId);
                    setActiveTab('rag');
                  }}
                />
              )}

              {activeTab === 'documents' && (
                <DocumentList
                  documents={documents}
                  collections={collections}
                  onSelectDocument={(doc) => setSelectedDocument(doc)}
                  onRefresh={handleRefreshCurrentWorkspace}
                  onAskAgent={(docId) => {
                    setRagScopedDocId(docId);
                    setActiveTab('rag');
                  }}
                />
              )}

              {activeTab === 'activity' && (
                <IngestionActivityView
                  jobs={jobs}
                  onRefresh={handleRefreshCurrentWorkspace}
                />
              )}

              {activeTab === 'rag' && currentWorkspace && (
                <GovernedRAGView
                  workspaceId={currentWorkspace.id}
                  documents={documents}
                  initialDocumentId={ragScopedDocId}
                />
              )}

              {activeTab === 'review' && (
                <ReviewQueueView
                  documents={reviewDocs}
                  onRefresh={handleRefreshCurrentWorkspace}
                  onInspectDocument={(doc) => setSelectedDocument(doc)}
                />
              )}

              {activeTab === 'audit' && (
                <AuditView
                  events={auditEvents}
                  onRefresh={handleRefreshCurrentWorkspace}
                />
              )}

              {(activeTab === 'settings' || activeTab === 'api_connect' || activeTab === 'mcp_server') && (
                <OrganizationSettingsView
                  currentOrg={currentOrg}
                  userRole={currentOrg?.role}
                  onRefreshOrg={handleRefreshCurrentWorkspace}
                  initialSection={activeTab === 'api_connect' ? 'api' : activeTab === 'mcp_server' ? 'mcp' : 'all'}
                />
              )}
            </>
          )}
        </main>
      </div>

      {/* Auth Modal (shown when requested or switching profiles) */}
      {isAuthModalOpen && (
        <AuthModal
          onSuccess={(data) => {
            setIsAuthModalOpen(false);
            handleAuthSuccess(data, false);
          }}
          onClose={() => setIsAuthModalOpen(false)}
        />
      )}

      {/* Upload Modal */}
      {currentWorkspace && (
        <UploadModal
          isOpen={isUploadModalOpen}
          onClose={() => setIsUploadModalOpen(false)}
          workspaceId={currentWorkspace.id}
          collections={collections}
          onUploadSuccess={handleUploadSuccess}
        />
      )}

      {/* Document Detail & OCR Inspector Modal */}
      <DocumentDetailModal
        document={selectedDocument}
        onClose={() => setSelectedDocument(null)}
        onReprocessSuccess={handleRefreshCurrentWorkspace}
      />
    </div>
  );
}
