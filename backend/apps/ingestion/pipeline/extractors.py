import io
import csv
import logging
import os
import re
import threading
import zipfile
import xml.etree.ElementTree as ET
from typing import Dict, Any, List, Optional, Tuple
from .ocr import OCRRouter, BaseOCRProvider

logger = logging.getLogger(__name__)

class DocxExtractor:
    """Extracts structured text, headings, and tables from DOCX documents."""
    @staticmethod
    def extract(file_path_or_bytes) -> List[Dict[str, Any]]:
        import docx
        if isinstance(file_path_or_bytes, (bytes, bytearray)):
            doc = docx.Document(io.BytesIO(file_path_or_bytes))
        else:
            doc = docx.Document(file_path_or_bytes)

        lines = []
        # Extract paragraphs with heading markers
        for p in doc.paragraphs:
            text = p.text.strip()
            if not text:
                continue
            style_name = getattr(p.style, 'name', '') or ''
            if style_name.startswith('Heading 1'):
                lines.append(f"# {text}")
            elif style_name.startswith('Heading 2'):
                lines.append(f"## {text}")
            elif style_name.startswith('Heading 3'):
                lines.append(f"### {text}")
            else:
                lines.append(text)

        # Extract tables
        for table in doc.tables:
            table_rows = []
            for row in table.rows:
                cells = [c.text.strip().replace('\n', ' ') for c in row.cells]
                table_rows.append(" | ".join(cells))
            if table_rows:
                lines.append("\n" + "\n".join(table_rows) + "\n")

        full_text = "\n\n".join(lines)
        return [{
            'page_number': 1,
            'text': full_text,
            'confidence': 1.0,
            'words_count': len(full_text.split()),
            'width': 612.0,
            'height': 792.0,
            'extraction_type': 'docx_extract',
            'engine': 'python-docx',
            'engine_version': '1.2.0',
            'is_repaired': False,
            'bounding_boxes': [],
        }]

class SpreadsheetExtractor:
    """Extracts tables, rows, and columns from CSV and XLSX documents."""
    @staticmethod
    def extract_csv(file_path_or_bytes) -> List[Dict[str, Any]]:
        if isinstance(file_path_or_bytes, (bytes, bytearray)):
            text = file_path_or_bytes.decode('utf-8', errors='replace')
            reader = csv.reader(io.StringIO(text))
            rows = list(reader)
        else:
            with open(file_path_or_bytes, 'r', encoding='utf-8', errors='replace') as f:
                reader = csv.reader(f)
                rows = list(reader)

        formatted_rows = [" | ".join(r) for r in rows if any(r)]
        full_text = "\n".join(formatted_rows)
        return [{
            'page_number': 1,
            'text': full_text,
            'confidence': 1.0,
            'words_count': len(full_text.split()),
            'width': 800.0,
            'height': 600.0,
            'extraction_type': 'csv_extract',
            'engine': 'csv_native',
            'engine_version': '1.0',
            'is_repaired': False,
            'bounding_boxes': [],
        }]

    @staticmethod
    def extract_xlsx(file_path_or_bytes) -> List[Dict[str, Any]]:
        import openpyxl
        try:
            if isinstance(file_path_or_bytes, (bytes, bytearray)):
                wb = openpyxl.load_workbook(io.BytesIO(file_path_or_bytes), data_only=True)
            else:
                wb = openpyxl.load_workbook(file_path_or_bytes, data_only=True)

            pages = []
            for idx, sheet_name in enumerate(wb.sheetnames):
                ws = wb[sheet_name]
                rows_data = []
                for row in ws.iter_rows(values_only=True):
                    if any(row):
                        str_cells = [str(c) if c is not None else "" for c in row]
                        rows_data.append(" | ".join(str_cells))
                text = f"## Sheet: {sheet_name}\n\n" + "\n".join(rows_data)
                pages.append({
                    'page_number': idx + 1,
                    'text': text,
                    'confidence': 1.0,
                    'words_count': len(text.split()),
                    'width': 800.0,
                    'height': 600.0,
                    'extraction_type': 'xlsx_extract',
                    'engine': 'openpyxl',
                    'engine_version': '3.1.5',
                    'is_repaired': False,
                    'bounding_boxes': [],
                })
            return pages if pages else TextExtractor.extract(file_path_or_bytes)
        except Exception:
            return TextExtractor.extract(file_path_or_bytes)

class PresentationExtractor:
    """
    Extracts structured presentation content from PPTX files:
    - Slide order and 1-indexed numbers (page_number).
    - Slide titles and text boxes with paragraph bullet hierarchies.
    - Tables formatted into clean Markdown tables.
    - Speaker notes extracted from linked notesSlide relationships.
    - Hyperlinks and presentation Dublin Core metadata.
    - Empty and corrupted presentation handling without throwing unhandled crashes.
    """
    @staticmethod
    def _safe_fromstring(xml_bytes: bytes):
        """Parses XML bytes safely, rejecting DTD/ENTITY declarations."""
        head = (xml_bytes or b"")[:65536].lower()
        if b"<!doctype" in head or b"<!entity" in head:
            raise ValueError("Unsafe XML DOCTYPE or ENTITY declaration rejected.")
        return ET.fromstring(xml_bytes)

    @staticmethod
    def _parse_rels(zf: zipfile.ZipFile, rels_path: str) -> Dict[str, Dict[str, str]]:
        rels = {}
        if rels_path not in zf.namelist():
            return rels
        try:
            tree = PresentationExtractor._safe_fromstring(zf.read(rels_path))
            for node in tree:
                if node.tag.endswith('}Relationship'):
                    r_id = node.attrib.get('Id')
                    target = node.attrib.get('Target', '')
                    r_type = node.attrib.get('Type', '')
                    if r_id:
                        rels[r_id] = {'target': target, 'type': r_type}
        except Exception:
            pass
        return rels

    @staticmethod
    def _parse_metadata(zf: zipfile.ZipFile) -> Dict[str, str]:
        meta = {}
        if 'docProps/core.xml' in zf.namelist():
            try:
                tree = PresentationExtractor._safe_fromstring(zf.read('docProps/core.xml'))
                for node in tree.iter():
                    tag = node.tag.split('}')[-1] if '}' in node.tag else node.tag
                    if tag in ('title', 'creator', 'lastModifiedBy', 'subject', 'description') and node.text:
                        meta[tag] = node.text.strip()
            except Exception:
                pass
        return meta

    @classmethod
    def _resolve_slide_order(cls, zf: zipfile.ZipFile) -> List[str]:
        ordered = []
        if 'ppt/presentation.xml' in zf.namelist() and 'ppt/_rels/presentation.xml.rels' in zf.namelist():
            try:
                pres_tree = cls._safe_fromstring(zf.read('ppt/presentation.xml'))
                pres_rels = cls._parse_rels(zf, 'ppt/_rels/presentation.xml.rels')

                for node in pres_tree.iter():
                    if node.tag.endswith('}sldId'):
                        r_id = node.attrib.get('{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id') or node.attrib.get('r:id') or node.attrib.get('id')
                        if r_id and r_id in pres_rels:
                            target = pres_rels[r_id]['target'].replace('\\', '/')
                            target = target.lstrip('/')
                            if not target.startswith('ppt/'):
                                target = f"ppt/{target}"
                            if target in zf.namelist():
                                ordered.append(target)
            except Exception:
                pass

        if not ordered:
            # Fallback to sorting filenames numerically
            slide_names = [n for n in zf.namelist() if re.match(r'ppt/slides/slide\d+\.xml', n)]
            def _get_num(s: str) -> int:
                m = re.search(r'\d+', s)
                return int(m.group(0)) if m else 0
            slide_names.sort(key=_get_num)
            ordered = slide_names

        return ordered

    @classmethod
    def _extract_slide_notes(cls, zf: zipfile.ZipFile, slide_name: str, slide_rels: Dict[str, Dict[str, str]]) -> str:
        notes_target = None
        for rel in slide_rels.values():
            if rel['type'].endswith('notesSlide'):
                notes_target = rel['target'].replace('\\', '/')
                break

        if not notes_target:
            return ''

        # Normalize relative path: e.g. ../notesSlides/notesSlide1.xml -> ppt/notesSlides/notesSlide1.xml
        base_dir = os.path.dirname(slide_name)
        norm_notes = os.path.normpath(os.path.join(base_dir, notes_target)).replace('\\', '/')
        if norm_notes not in zf.namelist():
            return ''

        try:
            tree = cls._safe_fromstring(zf.read(norm_notes))
            paragraphs = []
            for sp in tree.iter():
                if sp.tag.endswith('}sp'):
                    # Skip slide number and footer shapes
                    is_header_footer = False
                    for ph in sp.iter():
                        if ph.tag.endswith('}ph'):
                            ph_type = ph.attrib.get('type', '')
                            if ph_type in ('sldNum', 'hdr', 'ftr', 'dt'):
                                is_header_footer = True
                                break
                    if is_header_footer:
                        continue

                    sp_texts = []
                    for t in sp.iter():
                        if t.tag.endswith('}t') and t.text:
                            sp_texts.append(t.text.strip())
                    if sp_texts:
                        paragraphs.append(" ".join(sp_texts))
            return "\n\n".join(paragraphs).strip()
        except Exception:
            return ''

    @classmethod
    def extract(cls, file_path_or_bytes) -> List[Dict[str, Any]]:
        try:
            if isinstance(file_path_or_bytes, (bytes, bytearray)):
                stream = io.BytesIO(file_path_or_bytes)
            else:
                stream = file_path_or_bytes

            if not zipfile.is_zipfile(stream):
                return TextExtractor.extract(file_path_or_bytes)

            zf = zipfile.ZipFile(stream)
            ordered_slides = cls._resolve_slide_order(zf)

            if not ordered_slides:
                return [{
                    'page_number': 1,
                    'text': '# Presentation\n\n[Empty presentation or no slides found]',
                    'confidence': 1.0,
                    'words_count': 0,
                    'width': 960.0,
                    'height': 540.0,
                    'extraction_type': 'pptx_structured_extract',
                    'engine': 'openxml_pptx',
                    'engine_version': '2.0.0',
                    'is_repaired': False,
                    'bounding_boxes': []
                }]

            meta = cls._parse_metadata(zf)
            pres_header = ""
            if meta.get('title'):
                pres_header = f"Presentation: {meta['title']}\n"
                if meta.get('creator'):
                    pres_header += f"Author: {meta['creator']}\n"

            pages = []
            for idx, sname in enumerate(ordered_slides, 1):
                try:
                    xml_data = zf.read(sname)
                    root = cls._safe_fromstring(xml_data)
                except Exception:
                    pages.append({
                        'page_number': idx,
                        'text': f"# Slide {idx}\n\n[Corrupted slide data]",
                        'confidence': 0.0,
                        'words_count': 0,
                        'width': 960.0,
                        'height': 540.0,
                        'extraction_type': 'pptx_structured_extract',
                        'engine': 'openxml_pptx',
                        'engine_version': '2.0.0',
                        'is_repaired': False,
                        'bounding_boxes': []
                    })
                    continue

                # Load slide relationships for hyperlinks and speaker notes
                slide_dir = os.path.dirname(sname)
                slide_base = os.path.basename(sname)
                rels_path = f"{slide_dir}/_rels/{slide_base}.rels"
                slide_rels = cls._parse_rels(zf, rels_path)

                # Extract slide title
                slide_title = ""
                title_shapes = []
                for sp in root.iter():
                    if sp.tag.endswith('}sp'):
                        for ph in sp.iter():
                            if ph.tag.endswith('}ph'):
                                p_type = ph.attrib.get('type', '')
                                if p_type in ('title', 'ctrTitle', 'subTitle'):
                                    title_shapes.append(sp)
                                    break

                if title_shapes:
                    title_texts = []
                    for t in title_shapes[0].iter():
                        if t.tag.endswith('}t') and t.text:
                            title_texts.append(t.text.strip())
                    slide_title = " ".join(title_texts).strip()

                # Extract body paragraphs with bullet levels
                slide_paragraphs = []
                for sp in root.iter():
                    if sp.tag.endswith('}sp'):
                        if title_shapes and sp is title_shapes[0]:
                            continue  # Already extracted as title

                        for p in sp.iter():
                            if p.tag.endswith('}p'):
                                lvl = 0
                                for pPr in p.iter():
                                    if pPr.tag.endswith('}pPr'):
                                        lvl = int(pPr.attrib.get('lvl', 0))
                                        break

                                runs_text = []
                                for r in p.iter():
                                    if r.tag.endswith('}r'):
                                        hlink_url = ""
                                        for hlink in r.iter():
                                            if hlink.tag.endswith('}hlinkClick'):
                                                r_id = hlink.attrib.get('{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id') or hlink.attrib.get('r:id')
                                                if r_id and r_id in slide_rels:
                                                    hlink_url = slide_rels[r_id]['target']
                                                break

                                        t_text = "".join(t.text for t in r.iter() if t.tag.endswith('}t') and t.text)
                                        if t_text:
                                            if hlink_url:
                                                runs_text.append(f"[{t_text.strip()}]({hlink_url})")
                                            else:
                                                runs_text.append(t_text)

                                full_p = "".join(runs_text).strip()
                                if full_p:
                                    indent = "  " * lvl
                                    prefix = f"{indent}- " if lvl > 0 else ""
                                    slide_paragraphs.append(f"{prefix}{full_p}")

                # Extract tables
                markdown_tables = []
                for tbl in root.iter():
                    if tbl.tag.endswith('}tbl'):
                        rows = []
                        for tr in tbl.iter():
                            if tr.tag.endswith('}tr'):
                                cell_texts = []
                                for tc in tr.iter():
                                    if tc.tag.endswith('}tc'):
                                        t_words = [t.text.strip() for t in tc.iter() if t.tag.endswith('}t') and t.text]
                                        cell_texts.append(" ".join(t_words).replace('\n', ' ').replace('|', '\\|'))
                                if any(cell_texts):
                                    rows.append(cell_texts)

                        if rows:
                            max_cols = max(len(r) for r in rows)
                            normalized_rows = [r + [''] * (max_cols - len(r)) for r in rows]
                            header = "| " + " | ".join(normalized_rows[0]) + " |"
                            separator = "| " + " | ".join(['---'] * max_cols) + " |"
                            body_lines = ["| " + " | ".join(r) + " |" for r in normalized_rows[1:]]
                            markdown_tables.append("\n".join([header, separator] + body_lines))

                # Extract slide hyperlinks
                hyperlinks = []
                for rel in slide_rels.values():
                    target = rel.get('target', '')
                    if target.startswith(('http://', 'https://', 'mailto:')):
                        if target not in hyperlinks:
                            hyperlinks.append(target)

                # Extract speaker notes
                speaker_notes = cls._extract_slide_notes(zf, sname, slide_rels)

                # Assemble slide markdown
                slide_sections = []
                if idx == 1 and pres_header:
                    slide_sections.append(f"> {pres_header.strip()}\n")

                if slide_title:
                    slide_sections.append(f"# Slide {idx}: {slide_title}")
                else:
                    slide_sections.append(f"# Slide {idx}")

                if slide_paragraphs:
                    slide_sections.append("\n".join(slide_paragraphs))

                if markdown_tables:
                    for tbl_md in markdown_tables:
                        slide_sections.append("\n" + tbl_md + "\n")

                if hyperlinks:
                    links_md = "*Hyperlinks referenced:*\n" + "\n".join(f"- <{link}>" for link in hyperlinks)
                    slide_sections.append(links_md)

                if speaker_notes:
                    slide_sections.append(f"### Speaker Notes:\n{speaker_notes}")

                if len(slide_sections) == 1:
                    slide_sections.append("[Empty slide]")

                final_text = "\n\n".join(slide_sections).strip()

                pages.append({
                    'page_number': idx,
                    'text': final_text,
                    'confidence': 1.0,
                    'words_count': len(final_text.split()),
                    'width': 960.0,
                    'height': 540.0,
                    'extraction_type': 'pptx_structured_extract',
                    'engine': 'openxml_pptx',
                    'engine_version': '2.0.0',
                    'is_repaired': False,
                    'bounding_boxes': []
                })

            return pages
        except Exception:
            return TextExtractor.extract(file_path_or_bytes)


class HTMLExtractor:
    """Extracts clean, semantic Markdown/text from HTML files, eliminating script and styles to prevent hallucination."""
    @staticmethod
    def extract(file_path_or_bytes) -> List[Dict[str, Any]]:
        if isinstance(file_path_or_bytes, (bytes, bytearray)):
            raw_html = file_path_or_bytes.decode('utf-8', errors='replace')
        else:
            with open(file_path_or_bytes, 'r', encoding='utf-8', errors='replace') as f:
                raw_html = f.read()

        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(raw_html, 'html.parser')
            for tag in soup(['script', 'style', 'head', 'meta', 'link', 'svg', 'noscript']):
                tag.decompose()
            for h in soup.find_all(['h1', 'h2', 'h3', 'h4', 'h5', 'h6']):
                level = int(h.name[1])
                h.replace_with(f"\n\n{'#' * level} {h.get_text().strip()}\n")
            text = soup.get_text(separator="\n", strip=True)
        except Exception:
            text = re.sub(r'<(script|style)[^>]*>.*?</\1>', '', raw_html, flags=re.DOTALL | re.IGNORECASE)
            text = re.sub(r'<[^>]+>', ' ', text)
            text = re.sub(r'\s+', ' ', text).strip()

        return [{
            'page_number': 1,
            'text': text.strip(),
            'confidence': 1.0,
            'words_count': len(text.split()),
            'width': 612.0,
            'height': 792.0,
            'extraction_type': 'html_semantic_extract',
            'engine': 'bs4_semantic',
            'engine_version': '1.0',
            'is_repaired': False,
            'bounding_boxes': [],
        }]

class TextExtractor:
    """Extracts plain text and markdown files."""
    @staticmethod
    def extract(file_path_or_bytes) -> List[Dict[str, Any]]:
        if isinstance(file_path_or_bytes, (bytes, bytearray)):
            text = file_path_or_bytes.decode('utf-8', errors='replace')
        else:
            with open(file_path_or_bytes, 'r', encoding='utf-8', errors='replace') as f:
                text = f.read()

        return [{
            'page_number': 1,
            'text': text.strip(),
            'confidence': 1.0,
            'words_count': len(text.split()),
            'width': 612.0,
            'height': 792.0,
            'extraction_type': 'plaintext_extract',
            'engine': 'native_utf8',
            'engine_version': '1.0',
            'is_repaired': False,
            'bounding_boxes': [],
        }]

class UnifiedDocumentExtractor:
    """Dispatches extraction based on document type."""
    def __init__(
        self,
        ocr_provider: Optional[BaseOCRProvider] = None,
        pdf_visual_adapter: Optional[Any] = None,
    ):
        self.ocr_provider = ocr_provider
        self.router = OCRRouter(ocr_provider=ocr_provider)
        self.pdf_visual_adapter = pdf_visual_adapter

    @classmethod
    def with_pymupdf_visual(
        cls,
        ocr_provider: Optional[BaseOCRProvider] = None,
        **adapter_kwargs,
    ) -> "UnifiedDocumentExtractor":
        """Constructs a UnifiedDocumentExtractor adopting the PyMuPDF visual PDF adapter."""
        from .pdf_visual import PyMuPDFVisualPDFAdapter

        eff_ocr = ocr_provider
        adapter = PyMuPDFVisualPDFAdapter(ocr_provider=eff_ocr, **adapter_kwargs)
        return cls(ocr_provider=adapter.ocr_provider, pdf_visual_adapter=adapter)

    def _extract_pdf_with_adapter(self, file_path_or_bytes, filename: str = '') -> List[Dict[str, Any]]:
        if self.pdf_visual_adapter is None:
            return self.router.process_pdf(file_path_or_bytes)

        try:
            if hasattr(self.pdf_visual_adapter, 'process_pdf'):
                return self.pdf_visual_adapter.process_pdf(file_path_or_bytes)
            if hasattr(self.pdf_visual_adapter, 'enrich_page'):
                base_pages = self.router.process_pdf(file_path_or_bytes)
                return [
                    self.pdf_visual_adapter.enrich_page(
                        page,
                        raw_file=file_path_or_bytes,
                        context={'doc_type': 'pdf', 'filename': filename},
                    )
                    for page in base_pages
                ]
        except Exception as exc:
            logger.warning("pdf_visual_adapter failed; falling back cleanly to OCRRouter: %s", exc)

        return self.router.process_pdf(file_path_or_bytes)

    def _extract_image_with_adapter(self, file_path_or_bytes) -> List[Dict[str, Any]]:
        if self.pdf_visual_adapter is not None and hasattr(self.pdf_visual_adapter, 'process_image'):
            try:
                return self.pdf_visual_adapter.process_image(file_path_or_bytes)
            except Exception as exc:
                logger.warning("pdf_visual_adapter.process_image failed; falling back to OCRRouter: %s", exc)
        return self.router.process_image(file_path_or_bytes)

    def extract_document(self, file_path_or_bytes, doc_type: str, filename: str = '') -> List[Dict[str, Any]]:
        ext = os.path.splitext(filename.lower())[1] if filename else ''

        if doc_type == 'pdf' or ext == '.pdf':
            return self._extract_pdf_with_adapter(file_path_or_bytes, filename=filename)
        elif doc_type == 'image' or ext in ('.png', '.jpg', '.jpeg', '.tiff', '.tif', '.webp'):
            return self._extract_image_with_adapter(file_path_or_bytes)
        elif doc_type == 'docx' or ext == '.docx':
            return DocxExtractor.extract(file_path_or_bytes)
        elif ext == '.csv':
            return SpreadsheetExtractor.extract_csv(file_path_or_bytes)
        elif doc_type == 'spreadsheet' or ext in ('.xlsx', '.xls'):
            return SpreadsheetExtractor.extract_xlsx(file_path_or_bytes)
        elif doc_type == 'presentation' or ext in ('.pptx', '.ppt'):
            return PresentationExtractor.extract(file_path_or_bytes)
        elif ext in ('.html', '.htm'):
            return HTMLExtractor.extract(file_path_or_bytes)
        else:
            return TextExtractor.extract(file_path_or_bytes)


VISUAL_EXTENSIONS = {'.pdf', '.png', '.jpg', '.jpeg', '.tiff', '.tif', '.webp'}
LIGHTWEIGHT_EXTENSIONS = {'.docx', '.xlsx', '.xls', '.csv', '.pptx', '.ppt', '.txt', '.md', '.html', '.htm', '.json'}
VISUAL_DOC_TYPES = {'pdf', 'image'}
LIGHTWEIGHT_DOC_TYPES = {'docx', 'spreadsheet', 'presentation', 'txt', 'other'}


def classify_ingestion_workload(
    doc_type: str = '',
    filename: str = '',
    mime_type: str = '',
) -> str:
    """
    Deterministically classifies an ingestion document into:
    - 'visual': PDFs and raster images routed through the heavy visual/OCR subsystem
    - 'lightweight': DOCX, XLSX, PPTX, CSV, HTML, and plaintext routed to native parsers
    """
    ext = os.path.splitext((filename or '').lower())[1]
    norm_type = (doc_type or '').strip().lower()
    norm_mime = (mime_type or '').strip().lower()

    if ext in LIGHTWEIGHT_EXTENSIONS or norm_type in ('docx', 'spreadsheet', 'presentation', 'txt'):
        return 'lightweight'
    if ext in VISUAL_EXTENSIONS or norm_type in VISUAL_DOC_TYPES:
        return 'visual'
    if norm_mime == 'application/pdf' or norm_mime.startswith('image/'):
        return 'visual'
    return 'lightweight'


def needs_visual_extraction(
    doc_type: str = '',
    filename: str = '',
    mime_type: str = '',
) -> Tuple[bool, str]:
    """
    Returns (requires_visual_subsystem, routing_reason).
    Ordinary Office documents (DOCX, XLSX, PPTX, CSV) stay strictly on native parsers.
    """
    workload = classify_ingestion_workload(doc_type=doc_type, filename=filename, mime_type=mime_type)
    if workload == 'visual':
        ext = os.path.splitext((filename or '').lower())[1]
        if (doc_type or '').lower() == 'image' or ext in {'.png', '.jpg', '.jpeg', '.tiff', '.tif', '.webp'}:
            return True, 'image_visual_ocr'
        return True, 'pdf_incremental_visual_pipeline'
    return False, 'native_office_or_text_parser'


class WorkerExtractorRegistry:
    """
    Process-scoped, thread-safe extractor cache so heavy visual models
    (PyMuPDF adapter, Tesseract, PP-DocLayout-S, SLANet_plus) are loaded at most
    once per Celery worker process and reused across batch tasks.
    """

    _lock = threading.RLock()
    _instances: Dict[Tuple[int, str], UnifiedDocumentExtractor] = {}
    _init_counts: Dict[Tuple[int, str], int] = {}

    @classmethod
    def get_lightweight_extractor(cls) -> UnifiedDocumentExtractor:
        pid = os.getpid()
        key = (pid, 'lightweight')
        with cls._lock:
            inst = cls._instances.get(key)
            if inst is None:
                inst = UnifiedDocumentExtractor(pdf_visual_adapter=None)
                cls._instances[key] = inst
                cls._init_counts[key] = cls._init_counts.get(key, 0) + 1
            return inst

    @classmethod
    def get_visual_extractor(cls) -> UnifiedDocumentExtractor:
        pid = os.getpid()
        key = (pid, 'visual')
        with cls._lock:
            inst = cls._instances.get(key)
            if inst is None:
                from .runtime import configure_visual_cpu_runtime

                configure_visual_cpu_runtime()
                try:
                    from .ocr import TesseractOCRProvider
                    from .pdf_visual import PDFSafetyLimits

                    shared_ocr = TesseractOCRProvider()
                    adapter_kwargs: Dict[str, Any] = {
                        'ocr_provider': shared_ocr,
                        'limits': PDFSafetyLimits.from_settings_or_env(),
                        'analyze_searchable_with_layout': False,
                    }
                    try:
                        from .charts import PyMuPDFOpenCVChartExtractor
                        adapter_kwargs['chart_extractor'] = PyMuPDFOpenCVChartExtractor(ocr_provider=shared_ocr)
                    except Exception:
                        pass
                    try:
                        from .forms import FormKVExtractor
                        adapter_kwargs['form_extractor'] = FormKVExtractor(ocr_provider=shared_ocr)
                    except Exception:
                        pass
                    try:
                        from .tables import SLANetPlusConfig, SLANetPlusTableExtractor
                        adapter_kwargs['table_extractor'] = SLANetPlusTableExtractor(
                            config=SLANetPlusConfig.from_settings_or_env(),
                            ocr_provider=shared_ocr,
                        )
                    except Exception:
                        pass
                    try:
                        from .layout import PPDocLayoutSConfig, PPDocLayoutSProvider
                        adapter_kwargs['layout_provider'] = PPDocLayoutSProvider(
                            config=PPDocLayoutSConfig.from_settings_or_env(),
                            ocr_provider=shared_ocr,
                            table_extractor=adapter_kwargs.get('table_extractor'),
                            chart_extractor=adapter_kwargs.get('chart_extractor'),
                            form_extractor=adapter_kwargs.get('form_extractor'),
                        )
                    except Exception:
                        pass
                    inst = UnifiedDocumentExtractor.with_pymupdf_visual(**adapter_kwargs)
                except Exception as exc:
                    logger.warning(
                        "Failed to initialize worker visual extractor; falling back to OCRRouter extractor: %s",
                        exc,
                    )
                    inst = UnifiedDocumentExtractor(pdf_visual_adapter=None)
                cls._instances[key] = inst
                cls._init_counts[key] = cls._init_counts.get(key, 0) + 1
            return inst

    @classmethod
    def get_extractor_for_document(
        cls,
        doc_type: str = '',
        filename: str = '',
        mime_type: str = '',
        force_visual: Optional[bool] = None,
    ) -> UnifiedDocumentExtractor:
        use_visual = (
            force_visual
            if force_visual is not None
            else (classify_ingestion_workload(doc_type=doc_type, filename=filename, mime_type=mime_type) == 'visual')
        )
        if use_visual:
            return cls.get_visual_extractor()
        return cls.get_lightweight_extractor()

    @classmethod
    def get_stats(cls) -> Dict[str, Any]:
        pid = os.getpid()
        with cls._lock:
            return {
                'pid': pid,
                'cached_profiles': [k[1] for k in cls._instances if k[0] == pid],
                'init_counts': {k[1]: v for k, v in cls._init_counts.items() if k[0] == pid},
            }

    @classmethod
    def clear(cls) -> None:
        with cls._lock:
            cls._instances.clear()
            cls._init_counts.clear()
