"""
LORE Ephemeral Document Extraction Module.

Extracts uploaded documents (PDF, DOCX, XLSX, images, etc.) in-memory for ad-hoc
governance evaluations, proposal audits, and compliance reviews during chat turns.

CRITICAL ARCHITECTURAL INVARIANT:
Documents extracted through this module are ephemeral targets of inquiry. They are
NEVER persisted to `SourceDocument`, NEVER chunked into `DocumentChunk`, and NEVER
indexed into the Qdrant vector database or knowledge base.
"""

from __future__ import annotations

import io
import logging
import os
from typing import Any, Dict, List, Optional, Tuple

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import UploadedFile

from apps.sources.services import StorageSecurityService
from apps.ingestion.pipeline.extractors import (
    WorkerExtractorRegistry,
    classify_ingestion_workload,
)

logger = logging.getLogger(__name__)

SUPPORTED_CHAT_EXTENSIONS = {
    '.pdf', '.docx', '.xlsx', '.xls', '.csv', '.pptx', '.png', '.jpg', '.jpeg', '.tiff', '.tif', '.webp', '.txt', '.md'
}


class EphemeralDocumentExtractionError(Exception):
    """Raised when an ephemeral chat document cannot be safely extracted."""
    pass


def extract_ephemeral_document(
    file_obj: Any,
    filename: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Extracts an ephemeral document entirely in-memory using LORE's unified extraction subsystem.

    For PDFs and raster images, runs the visual pipeline:
    - PyMuPDF native vector text & paths
    - PP-DocLayout-S region detection
    - SLANet_plus table cell reconstruction
    - OpenCV chart detection & axis calibration
    - FormKVExtractor spatial key-value mapping & checkboxes
    - Tesseract OCR with Bengali repair

    For Office documents (DOCX, XLSX, CSV, PPTX), runs native extractors.

    Returns a structured dictionary containing all extracted text, tables, forms,
    and charts for query-time compliance comparison.
    """
    eff_filename = filename or getattr(file_obj, 'name', 'uploaded_document')
    base_name, raw_ext = os.path.splitext(eff_filename)
    ext = raw_ext.lower()

    if ext not in SUPPORTED_CHAT_EXTENSIONS:
        raise ValidationError(
            f"Unsupported document format '{ext}'. Supported formats: PDF, DOCX, XLSX, CSV, PPTX, PNG, JPG, TXT."
        )

    # 1. Run strict security checks on raw byte stream
    # (Inspects for zip bombs, path traversals, active JS/Launch in PDF, macros in OOXML, XXE)
    try:
        StorageSecurityService.inspect_and_validate(file_obj)
    except ValidationError:
        raise
    except Exception as sec_err:
        logger.warning(f"Security validation pre-flight warning for {eff_filename}: {sec_err}")

    # Read bytes safely
    if hasattr(file_obj, 'read'):
        try:
            file_obj.seek(0)
            raw_bytes = file_obj.read()
        finally:
            try:
                file_obj.seek(0)
            except Exception:
                pass
    elif isinstance(file_obj, (bytes, bytearray)):
        raw_bytes = bytes(file_obj)
    else:
        raise ValidationError("Invalid file object provided for ephemeral extraction.")

    file_size = len(raw_bytes)
    if file_size == 0:
        raise ValidationError(f"Uploaded document '{eff_filename}' is empty.")

    # 2. Determine document type and route through WorkerExtractorRegistry
    if ext == '.pdf':
        doc_type = 'pdf'
    elif ext in ('.png', '.jpg', '.jpeg', '.tiff', '.tif', '.webp'):
        doc_type = 'image'
    elif ext == '.docx':
        doc_type = 'docx'
    elif ext in ('.xlsx', '.xls'):
        doc_type = 'spreadsheet'
    elif ext == '.csv':
        doc_type = 'csv'
    elif ext in ('.pptx', '.ppt'):
        doc_type = 'presentation'
    else:
        doc_type = 'text'

    workload_class = classify_ingestion_workload(doc_type=doc_type, filename=eff_filename)

    # Use process-reused cached extractor instance
    if workload_class == 'visual':
        extractor = WorkerExtractorRegistry.get_visual_extractor()
    else:
        extractor = WorkerExtractorRegistry.get_lightweight_extractor()

    try:
        pages_data = extractor.extract_document(
            file_path_or_bytes=raw_bytes,
            doc_type=doc_type,
            filename=eff_filename
        )
    except Exception as ext_err:
        logger.exception(f"Ephemeral extraction failed for {eff_filename}: {ext_err}")
        raise EphemeralDocumentExtractionError(f"Failed to extract text from '{eff_filename}': {ext_err}") from ext_err

    if not pages_data:
        pages_data = [{
            'page_number': 1,
            'text': '',
            'words_count': 0,
            'confidence': 0.0,
            'visual_regions': [],
        }]

    # 3. Aggregate text, markdown tables, form fields, and charts
    text_chunks: List[str] = []
    tables_collected: List[Dict[str, Any]] = []
    forms_collected: List[Dict[str, Any]] = []
    charts_collected: List[Dict[str, Any]] = []
    total_words = 0
    confs: List[float] = []

    for p in pages_data:
        if not isinstance(p, dict):
            continue
        p_num = p.get('page_number', 1)
        p_text = str(p.get('text') or '').strip()
        if p_text:
            text_chunks.append(f"--- [Page {p_num}] ---\n{p_text}")
        words_val = p.get('words_count')
        if isinstance(words_val, (int, float)):
            total_words += int(words_val)
        elif isinstance(words_val, str) and words_val.isdigit():
            total_words += int(words_val)
        else:
            total_words += len(p_text.split())

        c_val = p.get('confidence')
        if isinstance(c_val, (int, float)) and c_val > 0:
            confs.append(float(c_val))

        # Collect visual regions (tables, charts, forms)
        v_regions = p.get('visual_regions')
        if isinstance(v_regions, list):
            for r in v_regions:
                if not isinstance(r, dict):
                    continue
                r_type = str(r.get('region_type') or r.get('type') or '')
                md = str(r.get('markdown') or r.get('content') or '')

                if 'table' in r_type.lower():
                    tables_collected.append({
                        'page_number': p_num,
                        'markdown': md,
                        'region_id': r.get('region_id'),
                        'confidence': r.get('confidence', 0.9),
                    })
                    if md and md not in p_text:
                        text_chunks.append(f"[Table on Page {p_num}]:\n{md}")
                elif 'chart' in r_type.lower():
                    c_meta = r.get('metadata', {})
                    chart_dict = c_meta.get('chart', {}) if isinstance(c_meta, dict) else {}
                    charts_collected.append({
                        'page_number': p_num,
                        'markdown': md,
                        'chart_type': chart_dict.get('chart_type', 'chart') if isinstance(chart_dict, dict) else 'chart',
                        'series': chart_dict.get('series', []) if isinstance(chart_dict, dict) else [],
                        'title': r.get('title') or md[:80],
                    })
                    if md and md not in p_text:
                        text_chunks.append(f"[Chart on Page {p_num}]:\n{md}")
                elif 'form' in r_type.lower() or 'field' in r_type.lower():
                    f_meta = r.get('metadata', {})
                    form_dict = f_meta.get('form', {}) if isinstance(f_meta, dict) else {}
                    forms_collected.append({
                        'page_number': p_num,
                        'fields': form_dict.get('fields', []) if isinstance(form_dict, dict) else [],
                        'checkboxes': form_dict.get('checkboxes', []) if isinstance(form_dict, dict) else [],
                        'markdown': md,
                    })
                    if md and md not in p_text:
                        text_chunks.append(f"[Form Fields on Page {p_num}]:\n{md}")

    combined_text = "\n\n".join(text_chunks).strip()
    avg_conf = round(sum(confs) / len(confs), 3) if confs else 0.95

    # 4. Formulate concise extraction summary
    summary_parts = [
        f"Document '{eff_filename}' ({doc_type.upper()})",
        f"{len(pages_data)} page(s)",
        f"{total_words} words",
    ]
    if tables_collected:
        summary_parts.append(f"{len(tables_collected)} table(s)")
    if charts_collected:
        summary_parts.append(f"{len(charts_collected)} chart(s)")
    if forms_collected:
        summary_parts.append(f"{len(forms_collected)} form section(s)")

    summary_str = ", ".join(summary_parts)

    return {
        'filename': eff_filename,
        'file_size': file_size,
        'doc_type': doc_type,
        'workload_class': workload_class,
        'pages_count': len(pages_data),
        'word_count': total_words,
        'ocr_confidence': avg_conf,
        'text': combined_text,
        'summary': summary_str,
        'tables': tables_collected,
        'charts': charts_collected,
        'forms': forms_collected,
        'pages_detail': [
            {
                'page_number': p.get('page_number', 1) if isinstance(p, dict) else 1,
                'word_count': p.get('words_count', 0) if isinstance(p, dict) else 0,
                'text_snippet': str(p.get('text') or '')[:200] if isinstance(p, dict) else '',
            }
            for p in pages_data
            if isinstance(p, dict)
        ],
    }

