'use client';

import React, { createContext, useContext, useEffect, useState } from 'react';

export type Language = 'en' | 'bn';

interface I18nContextType {
  language: Language;
  setLanguage: (lang: Language) => void;
  toggleLanguage: () => void;
  t: (key: string, fallback?: string) => string;
}

const STORAGE_KEY = 'lore-lang';

const translations: Record<Language, Record<string, string>> = {
  en: {
    // Common
    'app.name': 'LORE',
    'app.tagline': 'Enterprise Knowledge Grid',
    'common.save': 'Save',
    'common.cancel': 'Cancel',
    'common.delete': 'Delete',
    'common.confirm': 'Confirm',
    'common.upload': 'Upload Document',
    'common.search': 'Search',
    'common.filter': 'Filter',
    'common.refresh': 'Refresh',
    'common.close': 'Close',
    'common.back': 'Back',
    'common.processing': 'Processing',
    'common.ready': 'Ready',
    'common.needs_review': 'Needs Review',
    'common.failed': 'Failed',
    'common.quarantined': 'Quarantined',
    'common.retry': 'Retry',
    'common.view_details': 'View Details',
    'common.no_docs': 'No documents found',
    'common.loading': 'Loading...',
    'common.actions': 'Actions',
    'common.status': 'Status',
    'common.active': 'Active',
    'common.idle': 'Idle',

    // Navigation
    'nav.workspace_overview': 'Workspace Overview',
    'nav.live_ocr': 'Live OCR Studio',
    'nav.all_documents': 'All Documents',
    'nav.ingestion_activity': 'Ingestion Activity',
    'nav.governed_rag': 'Governed Search & RAG',
    'nav.review_queue': 'Review Queue',
    'nav.audit_ledger': 'Audit Ledger',
    'nav.settings': 'Organization & SaaS',
    'nav.knowledge_workspace': 'Knowledge Workspace',
    'nav.anti_hallucination': 'Anti-Hallucination Active',
    'nav.anti_hallucination_desc': 'Deterministic 9-state governance gate with source authority enforcement.',

    // Header
    'header.select_workspace': 'Select Workspace',
    'header.organization': 'Organization',
    'header.available_workspaces': 'Available Workspaces',
    'header.search_placeholder': 'Ask or search knowledge...',
    'header.upload_button': 'Upload Document',
    'header.guest_mode': 'Guest Mode (All Features Active)',
    'header.sign_in': 'Sign In / Switch Persona',
    'header.sign_out': 'Sign Out',
    'header.role': 'Role',

    // Overview
    'overview.badge': 'Northstar Digital Workspace • Active',
    'overview.hero_title': 'Enterprise Knowledge Workspace & Governed RAG',
    'overview.hero_desc': 'Welcome to LORE Enterprise. Your unstructured documents, scanned deeds, and contracts are normalized through dual-stream OCR, structure-aware chunking, and deterministic governance.',
    'overview.ask_rag': 'Ask Governed RAG',
    'overview.total_documents': 'Total Documents',
    'overview.ready_searchable': 'Ready & Searchable',
    'overview.processing_jobs': 'Processing Jobs',
    'overview.active_workers': 'active workers',
    'overview.pipeline_idle': 'Pipeline idle / ready',
    'overview.needs_review': 'Needs Review',
    'overview.flagged_verification': 'Flagged for verification',
    'overview.audit_events': 'Audit Events',
    'overview.immutable_trail': 'Immutable trail logged',
    'overview.recent_activity': 'Recent Document Activity',
    'overview.view_all_docs': 'View All Documents',
    'overview.pipeline_status': 'Ingestion Pipeline Status',
    'overview.view_activity_log': 'View Activity Log',
    'overview.pipeline_idle_ready': 'Pipeline is completely idle and ready for ingestion.',

    // Documents
    'docs.search_placeholder': 'Search documents by title or text...',
    'docs.all_collections': 'All Collections',
    'docs.all_statuses': 'All Statuses',
    'docs.title': 'Document Title',
    'docs.collection': 'Collection',
    'docs.pages': 'Pages',
    'docs.created': 'Created',
    'docs.inspect': 'Inspect',
    'docs.reprocess': 'Reprocess',
    'docs.empty_title': 'No documents found in workspace',
    'docs.empty_desc': 'Upload scanned PDF deeds, contracts, or text records to start ingestion.',

    // Upload Modal
    'upload.modal_title': 'Upload Documents to Knowledge Grid',
    'upload.modal_desc': 'Select or drag multiple files here to begin dual-stream OCR & ingestion pipeline.',
    'upload.drag_drop': 'Drag & drop documents here (multiple supported)',
    'upload.or_browse': 'or click to browse files from computer',
    'upload.supported_formats': 'Supported formats: PDF, DOCX, XLSX, CSV, PPTX, Images (PNG, JPG, TIFF, WEBP), Markdown, Text, HTML (up to 50MB each)',
    'upload.collection_label': 'Target Collection',
    'upload.default_collection': 'Default Collection',
    'upload.bilingual_ocr_toggle': 'Enable Dual-Stream Bengali OCR (BanglaOCR + Tesseract Engine)',
    'upload.start_btn': 'Start Ingestion Pipeline',
    'upload.processing_btn': 'Uploading & Ingesting...',
    'upload.files_selected': 'files selected',
    'upload.add_more': 'Add more files',
    'upload.clear_all': 'Clear all',
    'upload.ingest_all': 'Ingest All Files',
    'upload.individual_titles': 'Document Titles (Anti-Hallucination Anchors)',
    'upload.ready_badge': 'Ready',
    'upload.ingesting_badge': 'Ingesting',
    'upload.indexed_badge': 'Ready / Indexed',
    'upload.error_badge': 'Failed',
    'upload.success_summary': 'Successfully uploaded and ingested documents into the knowledge grid.',

    // OCR Studio
    'ocr.title': 'Realtime Dual-Stream OCR Studio',
    'ocr.subtitle': 'Bengali & English High-Precision Document Extraction & Normalization Engine',
    'ocr.load_sample': 'Load Test Samples:',
    'ocr.sample_deed': 'Land Deed (সাফ কবলা)',
    'ocr.sample_bank': 'Audit & Bank Sheet',
    'ocr.sample_contract': 'Corporate Contract',
    'ocr.original_doc': 'Original Scanned Document',
    'ocr.extracted_text': 'Realtime Extracted & Normalized Text',
    'ocr.confidence': 'OCR Confidence',
    'ocr.save_to_grid': 'Save to Knowledge Grid',
    'ocr.ask_rag': 'Ask in Governed RAG',
    'ocr.drop_hint': 'Click or drop a document image / PDF to inspect OCR realtime',

    // Governed RAG
    'rag.title': 'Governed Knowledge Search & RAG',
    'rag.subtitle': 'Ask factual questions grounded strictly in authorized enterprise documents with anti-hallucination guardrails.',
    'rag.input_placeholder': 'Ask a question grounded in uploaded enterprise documents...',
    'rag.search_btn': 'Search & Answer',
    'rag.searching': 'Searching knowledge base & applying 9-state governance...',
    'rag.governed_answer': 'Governed Answer',
    'rag.evidence_citations': 'Citations & Grounded Evidence',
    'rag.verification_state': 'Governance State',
    'rag.source_authority': 'Source Authority',
    'rag.sample_questions': 'Recommended Inquiries:',
    'rag.sample_1': 'What is the schedule of property and CS khatian number in the deed?',
    'rag.sample_2': 'Who are the executing parties and what is the consideration amount?',
    'rag.sample_3': 'Are there any encumbrances, easements, or caveats registered?',

    // Review Queue
    'review.title': 'Review Queue & Evidence Verification',
    'review.subtitle': 'Documents flagged by the governance gate requiring human-in-the-loop verification.',
    'review.empty_title': 'Review Queue Clear',
    'review.empty_desc': 'No documents currently require human verification.',
    'review.approve_btn': 'Approve Document',
    'review.quarantine_btn': 'Quarantine / Flag',

    // Ingestion Activity
    'activity.title': 'Ingestion Activity & Job Pipeline',
    'activity.subtitle': 'Realtime monitoring of OCR, chunking, embedding, and indexing jobs.',
    'activity.job_id': 'Job ID',
    'activity.document': 'Document',
    'activity.stage': 'Stage',
    'activity.progress': 'Progress',
    'activity.started': 'Started',

    // Audit
    'audit.title': 'Enterprise Audit Ledger',
    'audit.subtitle': 'Immutable chronological audit trail of all ingestion, retrieval, and governance decisions.',
    'audit.timestamp': 'Timestamp',
    'audit.actor': 'Actor',
    'audit.action': 'Action',
    'audit.resource': 'Resource',
    'audit.details': 'Event Details',

    // Settings
    'settings.title': 'Organization & Workspace Settings',
    'settings.subtitle': 'Manage multi-tenant organization preferences, users, and security settings.',
    'settings.theme_section': 'Appearance & Theme',
    'settings.theme_desc': 'Switch between Light (Parrot & Cream) and Dark (Obsidian & Emerald).',
    'settings.lang_section': 'Language & Localization',
    'settings.lang_desc': 'Choose interface language between বাংলা (Bengali) and English.',
    'settings.light_mode': 'Light Mode (Parrot & Cream)',
    'settings.dark_mode': 'Dark Mode (Obsidian & Emerald)',
    'settings.bengali': 'বাংলা (Bengali)',
    'settings.english': 'English (EN)',
    'settings.api_keys': 'API Keys & Integration',
    'settings.members': 'Organization Members & Roles',
    'settings.api_connect_title': 'AI Inference & Custom API Connect',
    'settings.api_connect_desc': 'Connect your own Groq Cloud API key for ultra-fast, zero-hallucination inference powered by gpt-oss-120B.',
    'settings.groq_key_label': 'Groq Cloud API Key',
    'settings.model_label': 'Active Anti-Hallucination Model',
    'settings.test_connection': 'Test Connection',
    'settings.save_key': 'Save API Key',
    'settings.clear_key': 'Clear Key',
    'settings.mcp_title': 'LORE MCP Server Hub & Generator',
    'settings.mcp_desc': 'Create and export a Model Context Protocol (MCP) server to connect LORE Knowledge Grid with Claude Desktop, Cursor, and Windsurf.',
    'settings.copy_config': 'Copy Configuration',
    'settings.copied': 'Copied!',
    'settings.download_mcp': 'Download MCP Server Script'
  },
  bn: {
    // Common
    'app.name': 'এলওআরই',
    'app.tagline': 'নিয়ন্ত্রিত এন্টারপ্রাইজ জ্ঞানভাণ্ডার',
    'common.save': 'সংরক্ষণ করুন',
    'common.cancel': 'বাতিল',
    'common.delete': 'মুছে ফেলুন',
    'common.confirm': 'নিশ্চিত করুন',
    'common.upload': 'ডকুমেন্ট আপলোড',
    'common.search': 'অনুসন্ধান',
    'common.filter': 'ফিল্টার',
    'common.refresh': 'রিফ্রেশ',
    'common.close': 'বন্ধ করুন',
    'common.back': 'ফিরে যান',
    'common.processing': 'প্রক্রিয়াকরণ চলছে',
    'common.ready': 'প্রস্তুত',
    'common.needs_review': 'পর্যালোচনা প্রয়োজন',
    'common.failed': 'ব্যর্থ',
    'common.quarantined': 'কোয়ারেন্টাইন',
    'common.retry': 'আবার চেষ্টা করুন',
    'common.view_details': 'বিস্তারিত দেখুন',
    'common.no_docs': 'কোনো ডকুমেন্ট পাওয়া যায়নি',
    'common.loading': 'লোড হচ্ছে...',
    'common.actions': 'পদক্ষেপ',
    'common.status': 'অবস্থা',
    'common.active': 'সক্রিয়',
    'common.idle': 'অপেক্ষমান',

    // Navigation
    'nav.workspace_overview': 'ওয়ার্কস্পেস ওভারভিউ',
    'nav.live_ocr': 'লাইভ ওসিআর স্টুডিও',
    'nav.all_documents': 'সকল ডকুমেন্ট',
    'nav.ingestion_activity': 'ইনজেশন কার্যক্রম',
    'nav.governed_rag': 'নিয়ন্ত্রিত সার্চ ও আরএজি',
    'nav.review_queue': 'পর্যালোচনার তালিকা',
    'nav.audit_ledger': 'অডিট লেজার',
    'nav.settings': 'প্রতিষ্ঠান ও সেটিংস',
    'nav.knowledge_workspace': 'নলেজ ওয়ার্কস্পেস',
    'nav.anti_hallucination': 'অ্যান্টি-হ্যালুসিনেশন সক্রিয়',
    'nav.anti_hallucination_desc': 'উৎস যাচাই ও ৯-স্তরের সুনির্দিষ্ট নিয়ন্ত্রণ ব্যবস্থা।',

    // Header
    'header.select_workspace': 'ওয়ার্কস্পেস নির্বাচন করুন',
    'header.organization': 'প্রতিষ্ঠান',
    'header.available_workspaces': 'বিদ্যমান ওয়ার্কস্পেসসমূহ',
    'header.search_placeholder': 'প্রশ্ন করুন বা জ্ঞানভাণ্ডার খুঁজুন...',
    'header.upload_button': 'ডকুমেন্ট আপলোড করুন',
    'header.guest_mode': 'গেস্ট মোড (সকল ফিচার সক্রিয়)',
    'header.sign_in': 'সাইন ইন / প্রোফাইল পরিবর্তন',
    'header.sign_out': 'সাইন আউট',
    'header.role': 'ভূমিকা',

    // Overview
    'overview.badge': 'নর্থস্টার ডিজিটাল ওয়ার্কস্পেস • সক্রিয়',
    'overview.hero_title': 'এন্টারপ্রাইজ জ্ঞানভাণ্ডার ও নিয়ন্ত্রিত আরএজি',
    'overview.hero_desc': 'এলওআরই (LORE) এন্টারপ্রাইজে স্বাগতম। আপনার অবিন্যস্ত নথি, স্ক্যান করা দলিল ও চুক্তিপত্র দ্বৈত-ধারা ওসিআর, স্ট্রাকচার্ড খণ্ডীকরণ ও সুনির্দিষ্ট নিয়ন্ত্রণের মাধ্যমে তথ্যভাণ্ডারে রূপান্তর হয়।',
    'overview.ask_rag': 'আরএজি-কে প্রশ্ন করুন',
    'overview.total_documents': 'মোট ডকুমেন্ট',
    'overview.ready_searchable': 'প্রস্তুত ও অনুসন্ধানযোগ্য',
    'overview.processing_jobs': 'প্রক্রিয়াকরণ কাজ',
    'overview.active_workers': 'সক্রিয় কর্মী',
    'overview.pipeline_idle': 'পাইপলাইন প্রস্তুত / নিষ্ক্রিয়',
    'overview.needs_review': 'পর্যালোচনা প্রয়োজন',
    'overview.flagged_verification': 'যাচাইয়ের জন্য চিহ্নিত',
    'overview.audit_events': 'অডিট ইভেন্ট',
    'overview.immutable_trail': 'অপরিবর্তনীয় রেকর্ড সংরক্ষিত',
    'overview.recent_activity': 'সাম্প্রতিক ডকুমেন্ট কার্যক্রম',
    'overview.view_all_docs': 'সকল ডকুমেন্ট দেখুন',
    'overview.pipeline_status': 'ইনজেশন পাইপলাইন অবস্থা',
    'overview.view_activity_log': 'অ্যাক্টিভিটি লগ দেখুন',
    'overview.pipeline_idle_ready': 'পাইপলাইন সম্পূর্ণ প্রস্তুত এবং নতুন নথির অপেক্ষায় রয়েছে।',

    // Documents
    'docs.search_placeholder': 'নাম বা বিষয়বস্তু দিয়ে ডকুমেন্ট খুঁজুন...',
    'docs.all_collections': 'সকল কালেকশন',
    'docs.all_statuses': 'সকল অবস্থা',
    'docs.title': 'ডকুমেন্টের নাম',
    'docs.collection': 'কালেকশন',
    'docs.pages': 'পৃষ্ঠা',
    'docs.created': 'তৈরির তারিখ',
    'docs.inspect': 'পরীক্ষা করুন',
    'docs.reprocess': 'পুনরায় প্রক্রিয়া করুন',
    'docs.empty_title': 'ওয়ার্কস্পেসে কোনো ডকুমেন্ট নেই',
    'docs.empty_desc': 'ইনজেশন শুরু করতে স্ক্যান করা পিডিএফ দলিল, চুক্তি বা ফাইল আপলোড করুন।',

    // Upload Modal
    'upload.modal_title': 'নলেজ গ্রিডে একাধিক ডকুমেন্ট আপলোড করুন',
    'upload.modal_desc': 'দ্বৈত-ধারা ওসিআর ও ইনজেশন শুরু করতে একাধিক ফাইল নির্বাচন করুন বা টেনে আনুন।',
    'upload.drag_drop': 'আপনার ডকুমেন্টগুলো এখানে টেনে আনুন (একাধিক ফাইল সমর্থিত)',
    'upload.or_browse': 'অথবা কম্পিউটার থেকে ফাইল ব্রাউজ করুন',
    'upload.supported_formats': 'সমর্থিত ফরম্যাট: PDF, DOCX, XLSX, CSV, PPTX, ছবি (PNG, JPG, TIFF, WEBP), Markdown, Text, HTML (প্রতিটি ৫০ মেগাবাইট পর্যন্ত)',
    'upload.collection_label': 'টার্গেট কালেকশন',
    'upload.default_collection': 'ডিফল্ট কালেকশন',
    'upload.bilingual_ocr_toggle': 'দ্বৈত-ধারা বাংলা ওসিআর সক্রিয় করুন (BanglaOCR + Tesseract ইঞ্জিন)',
    'upload.start_btn': 'ইনজেশন পাইপলাইন শুরু করুন',
    'upload.processing_btn': 'আপলোড ও ইনজেশন চলছে...',
    'upload.files_selected': 'টি ফাইল নির্বাচিত',
    'upload.add_more': 'আরও ফাইল যোগ করুন',
    'upload.clear_all': 'সব মুছুন',
    'upload.ingest_all': 'সকল ফাইল ইনজেস্ট করুন',
    'upload.individual_titles': 'ডকুমেন্ট শিরোনাম (হ্যালুসিনেশন রোধে সহায়ক)',
    'upload.ready_badge': 'প্রস্তুত',
    'upload.ingesting_badge': 'ইনজেশন চলছে',
    'upload.indexed_badge': 'ইনডেক্সড / প্রস্তুত',
    'upload.error_badge': 'ব্যর্থ',
    'upload.success_summary': 'সফলভাবে ডকুমেন্টগুলো নলেজ গ্রিডে ইনজেস্ট করা হয়েছে।',

    // OCR Studio
    'ocr.title': 'রিয়েল-টাইম দ্বৈত-ধারা ওসিআর স্টুডিও',
    'ocr.subtitle': 'বাংলা ও ইংরেজি উচ্চ-নির্ভুল নথি বিশ্লেষণ ও নিষ্কাশন ইঞ্জিন',
    'ocr.load_sample': 'পরীক্ষামূলক নমুনা লোড করুন:',
    'ocr.sample_deed': 'সাফ কবলা দলিল (ভূমি)',
    'ocr.sample_bank': 'অডিট ও ব্যাংক শিট',
    'ocr.sample_contract': 'কর্পোরেট চুক্তিপত্র',
    'ocr.original_doc': 'মূল স্ক্যান করা নথি',
    'ocr.extracted_text': 'রিয়েল-টাইমে নিষ্কাশিত ও সমন্বিত পাঠ্য',
    'ocr.confidence': 'ওসিআর নির্ভুলতা',
    'ocr.save_to_grid': 'নলেজ গ্রিডে সংরক্ষণ করুন',
    'ocr.ask_rag': 'আরএজিতে প্রশ্ন করুন',
    'ocr.drop_hint': 'রিয়েল-টাইমে ওসিআর পরীক্ষা করতে ডকুমেন্ট ড্রপ করুন বা ক্লিক করুন',

    // Governed RAG
    'rag.title': 'নিয়ন্ত্রিত জ্ঞান অনুসন্ধান ও আরএজি (RAG)',
    'rag.subtitle': 'অনুমোদিত এন্টারপ্রাইজ দলিলের তথ্যের ভিত্তিতে নির্ভরযোগ্য প্রশ্ন করুন (অ্যান্টি-হ্যালুসিনেশন সুরক্ষা সহ)।',
    'rag.input_placeholder': 'আপলোডকৃত নথির তথ্যের ভিত্তিতে একটি প্রশ্ন লিখুন...',
    'rag.search_btn': 'উত্তর খুঁজুন',
    'rag.searching': 'তথ্যভাণ্ডার অনুসন্ধান ও ৯-স্তরের যাচাইকরণ চলছে...',
    'rag.governed_answer': 'যাচাইকৃত উত্তর',
    'rag.evidence_citations': 'উদ্ধৃতি ও প্রামাণ্য তথ্য',
    'rag.verification_state': 'যাচাইকরণ অবস্থা',
    'rag.source_authority': 'উৎস কর্তৃত্ব স্তর',
    'rag.sample_questions': 'প্রস্তাবিত প্রশ্নাবলী:',
    'rag.sample_1': 'উক্ত দলিলে সম্পত্তির তফসিল এবং সিএস খতিয়ান নম্বর কত?',
    'rag.sample_2': 'সম্পাদনের পক্ষগণ কারা এবং সাফ কবলা মূল্যের পরিমাণ কত?',
    'rag.sample_3': 'দলিলে কোনো দায়বদ্ধতা বা স্বত্বাধিকারের শর্ত উল্লেখ আছে কি?',

    // Review Queue
    'review.title': 'পর্যালোচনার তালিকা ও তথ্য যাচাই',
    'review.subtitle': 'প্রশাসনিক নীতিমালার আওতায় মানব পর্যালোচনার জন্য চিহ্নিত নথিসমূহ।',
    'review.empty_title': 'পর্যালোচনার তালিকা খালি',
    'review.empty_desc': 'বর্তমানে কোনো নথি মানব পর্যালোচনার অপেক্ষায় নেই।',
    'review.approve_btn': 'ডকুমেন্ট অনুমোদন করুন',
    'review.quarantine_btn': 'কোয়ারেন্টাইন / ফ্ল্যাগ',

    // Ingestion Activity
    'activity.title': 'ইনজেশন কার্যক্রম ও কাজের পাইপলাইন',
    'activity.subtitle': 'ওসিআর, খণ্ডীকরণ, এম্বেডিং এবং ইনডেক্সিং কাজের রিয়েল-টাইম পর্যবেক্ষণ।',
    'activity.job_id': 'কাজের আইডি',
    'activity.document': 'ডকুমেন্ট',
    'activity.stage': 'ধাপ',
    'activity.progress': 'অগ্রগতি',
    'activity.started': 'শুরুর সময়',

    // Audit
    'audit.title': 'এন্টারপ্রাইজ অডিট লেজার',
    'audit.subtitle': 'সকল ইনজেশন, অনুসন্ধান এবং নীতিগত সিদ্ধান্তের অপরিবর্তনীয় ঐতিহাসিক রেকর্ড।',
    'audit.timestamp': 'সময়কাল',
    'audit.actor': 'ব্যবহারকারী/সিস্টেম',
    'audit.action': 'কর্মকাণ্ড',
    'audit.resource': 'রিসোর্স',
    'audit.details': 'ইভেন্টের বিবরণ',

    // Settings
    'settings.title': 'প্রতিষ্ঠান ও ওয়ার্কস্পেস সেটিংস',
    'settings.subtitle': 'মাল্টি-টেন্যান্ট প্রতিষ্ঠানের পছন্দসমূহ, সদস্য ও নিরাপত্তা ব্যবস্থা পরিচালনা করুন।',
    'settings.theme_section': 'দৃশ্যমানতা ও থিম',
    'settings.theme_desc': 'লাইট (প্যারট ও ক্রিম) এবং ডার্ক (অবসিডিয়ান ও এমারেল্ড)-এর মধ্যে নির্বাচন করুন।',
    'settings.lang_section': 'ভাষা ও লোকালাইজেশন',
    'settings.lang_desc': 'ইন্টারফেসের ভাষা নির্বাচন করুন (বাংলা অথবা ইংরেজি)।',
    'settings.light_mode': 'লাইট মোড (প্যারট ও ক্রিম)',
    'settings.dark_mode': 'ডার্ক মোড (অবসিডিয়ান ও এমারেল্ড)',
    'settings.bengali': 'বাংলা (Bengali)',
    'settings.english': 'English (ইংরেজি)',
    'settings.api_keys': 'এপিআই কি ও ইন্টিগ্রেশন',
    'settings.members': 'প্রতিষ্ঠানের সদস্য ও ভূমিকাসমূহ',
    'settings.api_connect_title': 'এআই ইঞ্জিন ও নিজস্ব এপিআই সংযোগ',
    'settings.api_connect_desc': 'দ্রুতগতির ও সম্পূর্ণ হ্যালুসিনেশন-মুক্ত উত্তরের জন্য নিজস্ব Groq এপিআই কি (gpt-oss-120B মডেল) যুক্ত করুন।',
    'settings.groq_key_label': 'Groq ক্লাউড এপিআই কি',
    'settings.model_label': 'সক্রিয় অ্যান্টি-হ্যালুসিনেশন মডেল',
    'settings.test_connection': 'সংযোগ পরীক্ষা করুন',
    'settings.save_key': 'এপিআই কি সংরক্ষণ করুন',
    'settings.clear_key': 'কি মুছুন',
    'settings.mcp_title': 'লর এমসিপি (MCP) সার্ভার নির্মাতা ও ইন্টিগ্রেশন',
    'settings.mcp_desc': 'ক্লড ডেস্কটপ, কার্সর ও উইন্ডসার্ফের সাথে লর জ্ঞানভাণ্ডার যুক্ত করতে মডেল কনটেক্সট প্রোটোকল (MCP) কনফিগারেশন তৈরি করুন।',
    'settings.copy_config': 'কনফিগারেশন কপি করুন',
    'settings.copied': 'কপি সম্পন্ন!',
    'settings.download_mcp': 'এমসিপি সার্ভার স্ক্রিপ্ট ডাউনলোড করুন'
  }
};

const I18nContext = createContext<I18nContextType | undefined>(undefined);

export const LanguageProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [language, setLanguageState] = useState<Language>('bn'); // Default to Bangla or read from localStorage

  useEffect(() => {
    try {
      const stored = localStorage.getItem(STORAGE_KEY) as Language | null;
      if (stored === 'bn' || stored === 'en') {
        setLanguageState(stored);
        document.documentElement.lang = stored;
      } else {
        document.documentElement.lang = 'bn';
      }
    } catch (e) {
      document.documentElement.lang = 'bn';
    }
  }, []);

  const setLanguage = (lang: Language) => {
    setLanguageState(lang);
    document.documentElement.lang = lang;
    try {
      localStorage.setItem(STORAGE_KEY, lang);
    } catch (e) {}
  };

  const toggleLanguage = () => {
    setLanguage(language === 'bn' ? 'en' : 'bn');
  };

  const t = (key: string, fallback?: string): string => {
    return translations[language]?.[key] || translations['en']?.[key] || fallback || key;
  };

  return (
    <I18nContext.Provider value={{ language, setLanguage, toggleLanguage, t }}>
      {children}
    </I18nContext.Provider>
  );
};

export const useI18n = (): I18nContextType => {
  const context = useContext(I18nContext);
  if (!context) {
    throw new Error('useI18n must be used within a LanguageProvider');
  }
  return context;
};
