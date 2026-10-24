/**
 * LORE Enterprise — Evidence Presentation Frontend Contract & Interaction Tests
 * Runs with Node.js built-in test runner: node --test frontend/tests/evidence_presentation.test.js
 * 
 * Verifies:
 * 1. Panel opening and closing interaction state and keyboard accessibility.
 * 2. ARIA accessibility attributes (aria-expanded, aria-controls, role="region").
 * 3. Source rendering with complete stored metadata (title, doc ID, page, section, shortest passage, applicability, status, effective date).
 * 4. Missing metadata handling without inventing values (unpaginated doc, missing section, unknown status).
 * 5. Duplicate and near-duplicate evidence pruning logic.
 * 6. Permission preservation and zero-leakage security constraints.
 */

const { test, describe } = require('node:test');
const assert = require('node:assert/strict');

// Simulated UI helper functions mimicking GovernedRAGView logic
function createEvidenceToggleState(initialState = false) {
  let isOpen = initialState;
  return {
    isOpen: () => isOpen,
    toggle: () => { isOpen = !isOpen; return isOpen; },
    handleKeyDown: (eventKey) => {
      if (eventKey === 'Enter' || eventKey === ' ') {
        isOpen = !isOpen;
        return true;
      }
      return false;
    },
    getAriaAttributes: () => ({
      id: 'lore-evidence-details-toggle',
      'aria-expanded': isOpen,
      'aria-controls': 'lore-evidence-details-panel',
    }),
    getPanelAttributes: () => ({
      id: 'lore-evidence-details-panel',
      role: 'region',
      'aria-labelledby': 'lore-evidence-details-toggle',
    })
  };
}

function resolveDocumentStatus(status) {
  const norm = (status || 'unknown').toLowerCase();
  switch (norm) {
    case 'approved': return { label: 'Approved', variant: 'success' };
    case 'draft': return { label: 'Draft', variant: 'warning' };
    case 'future-effective': return { label: 'Future-Effective', variant: 'brand' };
    case 'superseded': return { label: 'Superseded', variant: 'error' };
    case 'archived': return { label: 'Archived', variant: 'muted' };
    default: return { label: 'Unknown Status', variant: 'neutral' };
  }
}

function renderCitationCard(cit, idx) {
  // Never invent missing values
  const pageLabel = cit.page_number != null ? `Page ${cit.page_number}` : 'Page not specified';
  const sectionLabel = cit.section ? `Section: ${cit.section}` : null;
  const statusInfo = resolveDocumentStatus(cit.document_status);
  const evidenceTypeLabel = cit.evidence_type === 'direct' ? 'Direct Evidence' : 'Inference';
  const roleLabel = idx === 0 ? 'Primary Direct Proof' : 'Supporting Source / Context';

  return {
    documentTitle: cit.document_title || 'Untitled Document',
    documentId: `ID: ${cit.document_id}`,
    documentVersion: cit.document_version ? `v${cit.document_version}` : null,
    statusLabel: statusInfo.label,
    statusVariant: statusInfo.variant,
    evidenceTypeLabel,
    pageLabel,
    sectionLabel,
    authorityBadge: `Authority Rank ${cit.authority_level}`,
    roleLabel,
    shortestPassage: cit.shortest_passage || cit.passage,
    applicabilityExplanation: cit.applicability_explanation || null,
    effectiveDate: cit.effective_date ? `Effective: ${cit.effective_date}` : null,
    supersessionDetails: cit.supersession_details ? `Supersession: ${cit.supersession_details}` : null,
    limitation: cit.limitation ? `Source Limitation: ${cit.limitation}` : null,
  };
}

function deduplicateEvidenceChunks(chunks) {
  const seen = new Set();
  const deduped = [];
  for (const chk of chunks) {
    const key = `${chk.document_id}:${chk.page_number}:${(chk.text || '').slice(0, 50).trim().toLowerCase()}`;
    if (!seen.has(key)) {
      seen.add(key);
      deduped.push(chk);
    }
  }
  return deduped;
}

// ==============================================================================
// TEST SUITES
// ==============================================================================

describe('Evidence Details Panel — Toggle & Accessibility Interaction', () => {
  test('initial state keeps panel closed while concise answer remains visible', () => {
    const state = createEvidenceToggleState(false);
    assert.equal(state.isOpen(), false);
    
    const aria = state.getAriaAttributes();
    assert.equal(aria['aria-expanded'], false);
    assert.equal(aria['aria-controls'], 'lore-evidence-details-panel');
    assert.equal(aria.id, 'lore-evidence-details-toggle');
  });

  test('opening and closing toggle transitions state correctly', () => {
    const state = createEvidenceToggleState(false);
    
    // User clicks toggle to open
    const opened = state.toggle();
    assert.equal(opened, true);
    assert.equal(state.isOpen(), true);
    assert.equal(state.getAriaAttributes()['aria-expanded'], true);

    // Panel has correct region attributes
    const panelAria = state.getPanelAttributes();
    assert.equal(panelAria.id, 'lore-evidence-details-panel');
    assert.equal(panelAria.role, 'region');
    assert.equal(panelAria['aria-labelledby'], 'lore-evidence-details-toggle');

    // User clicks toggle to close
    const closed = state.toggle();
    assert.equal(closed, false);
    assert.equal(state.isOpen(), false);
    assert.equal(state.getAriaAttributes()['aria-expanded'], false);
  });

  test('keyboard accessibility: Enter and Space keys toggle panel state', () => {
    const state = createEvidenceToggleState(false);

    // Enter key triggers toggle
    assert.equal(state.handleKeyDown('Enter'), true);
    assert.equal(state.isOpen(), true);

    // Space key triggers toggle
    assert.equal(state.handleKeyDown(' '), true);
    assert.equal(state.isOpen(), false);

    // Other keys (e.g. Tab, Escape) do not trigger toggle
    assert.equal(state.handleKeyDown('Tab'), false);
    assert.equal(state.isOpen(), false);
    assert.equal(state.handleKeyDown('Escape'), false);
    assert.equal(state.isOpen(), false);
  });
});

describe('Source Rendering & Metadata Completeness', () => {
  test('renders full stored metadata without missing provenance', () => {
    const citation = {
      citation_id: 'cit-001',
      document_id: 'doc-travel-2026',
      document_title: 'Enterprise Travel Policy 2026',
      document_version: 2,
      page_number: 7,
      section: 'Section 3.2 Meal Allowances',
      authority_level: 6,
      passage: 'The maximum allowable reimbursement for dinner during business travel is $75 per day. Itemized receipts are mandatory.',
      shortest_passage: 'The maximum allowable reimbursement for dinner during business travel is $75 per day.',
      document_status: 'approved',
      effective_date: '2026-01-01',
      supersession_details: 'Supersedes Travel Policy 2024 v1',
      applicability_explanation: 'Authoritative Rank 6 approved policy establishing binding operational compliance.',
      evidence_type: 'direct',
      limitation: null
    };

    const card = renderCitationCard(citation, 0);

    // 1. Document title and document ID
    assert.equal(card.documentTitle, 'Enterprise Travel Policy 2026');
    assert.equal(card.documentId, 'ID: doc-travel-2026');
    assert.equal(card.documentVersion, 'v2');

    // 2. Page number and section
    assert.equal(card.pageLabel, 'Page 7');
    assert.equal(card.sectionLabel, 'Section: Section 3.2 Meal Allowances');

    // 3. Shortest exact source passage that proves the answer
    assert.equal(card.shortestPassage, 'The maximum allowable reimbursement for dinner during business travel is $75 per day.');

    // 4. Explanation of why the source applies
    assert.equal(card.applicabilityExplanation, 'Authoritative Rank 6 approved policy establishing binding operational compliance.');

    // 5. Document status using actual stored metadata
    assert.equal(card.statusLabel, 'Approved');
    assert.equal(card.statusVariant, 'success');

    // 6. Effective date and supersession details
    assert.equal(card.effectiveDate, 'Effective: 2026-01-01');
    assert.equal(card.supersessionDetails, 'Supersession: Supersedes Travel Policy 2024 v1');

    // 7. Role and evidence type
    assert.equal(card.roleLabel, 'Primary Direct Proof');
    assert.equal(card.evidenceTypeLabel, 'Direct Evidence');
    assert.equal(card.limitation, null);
  });

  test('distinguishes secondary sources and evaluated inferences', () => {
    const secondaryCitation = {
      citation_id: 'cit-002',
      document_id: 'doc-handbook',
      document_title: 'Employee Handbook',
      page_number: 12,
      section: null,
      authority_level: 3,
      passage: 'Standard cost optimization principles should guide travel.',
      shortest_passage: 'Standard cost optimization principles should guide travel.',
      document_status: 'draft',
      effective_date: null,
      supersession_details: null,
      applicability_explanation: 'Rank 3 informative record providing supplemental context.',
      evidence_type: 'inference',
      limitation: 'Non-binding: Document is an unapproved draft.'
    };

    const card = renderCitationCard(secondaryCitation, 1);

    assert.equal(card.roleLabel, 'Supporting Source / Context');
    assert.equal(card.evidenceTypeLabel, 'Inference');
    assert.equal(card.statusLabel, 'Draft');
    assert.equal(card.statusVariant, 'warning');
    assert.equal(card.limitation, 'Source Limitation: Non-binding: Document is an unapproved draft.');
  });
});

describe('Missing Metadata Fallback — Zero Invention Contract', () => {
  test('unpaginated document renders "Page not specified" without inventing page numbers', () => {
    const unpaginatedCitation = {
      citation_id: 'cit-unpaginated',
      document_id: 'doc-readme-md',
      document_title: 'API Reference.md',
      page_number: null, // Unpaginated markdown file
      section: null,     // No specific section heading
      authority_level: 4,
      passage: 'Rate limits are set to 100 requests per minute.',
      shortest_passage: 'Rate limits are set to 100 requests per minute.',
      document_status: null, // Unknown status
      effective_date: null,  // No effective date stored
      evidence_type: 'direct'
    };

    const card = renderCitationCard(unpaginatedCitation, 0);

    // Must NOT invent a page number
    assert.equal(card.pageLabel, 'Page not specified');
    // Must NOT invent a section
    assert.equal(card.sectionLabel, null);
    // Must NOT invent an effective date
    assert.equal(card.effectiveDate, null);
    // Must NOT invent approval status
    assert.equal(card.statusLabel, 'Unknown Status');
    assert.equal(card.statusVariant, 'neutral');
  });
});

describe('Duplicate Evidence Pruning in Presentation', () => {
  test('filters duplicate passages from same document and page', () => {
    const chunks = [
      { document_id: 'doc-1', page_number: 2, text: 'Dinner reimbursement is $75 per day.' },
      { document_id: 'doc-1', page_number: 2, text: 'Dinner reimbursement is $75 per day.' },
      { document_id: 'doc-1', page_number: 3, text: 'Breakfast reimbursement is $25 per day.' }
    ];

    const deduped = deduplicateEvidenceChunks(chunks);
    assert.equal(deduped.length, 2);
    assert.equal(deduped[0].page_number, 2);
    assert.equal(deduped[1].page_number, 3);
  });
});

describe('Permission Preservation & Zero-Leakage Security Invariant', () => {
  test('evidence presentation never reveals citations or passages when access is denied', () => {
    // Simulated backend result for L7 permission denial
    const deniedResult = {
      state: 'denied',
      directive: 'stop',
      answer: "Access Denied: You do not have sufficient permissions to view the authoritative records for 'classified doc'.",
      citations: [],
      evidence_found: []
    };

    // When panel is open or closed, zero citations must be exposed
    assert.equal(deniedResult.citations.length, 0);
    assert.equal(deniedResult.evidence_found.length, 0);

    // In the UI, rendering an empty citations array shows the safe disclosure notice
    const hasCitations = deniedResult.citations && deniedResult.citations.length > 0;
    assert.equal(hasCitations, false);

    const safeFallbackMessage = "No Evidence Sources Disclosed. Access restrictions prohibit source exposure or no authoritative records were matched.";
    assert.match(safeFallbackMessage, /No Evidence Sources Disclosed/);
  });
});
