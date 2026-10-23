import io
import csv
import os
import re
import zipfile
import xml.etree.ElementTree as ET
from typing import Dict, Any, List
from .ocr import OCRRouter, BaseOCRProvider

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
            if p.style.name.startswith('Heading 1'):
                lines.append(f"# {text}")
            elif p.style.name.startswith('Heading 2'):
                lines.append(f"## {text}")
            elif p.style.name.startswith('Heading 3'):
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
        else:
            with open(file_path_or_bytes, 'r', encoding='utf-8', errors='replace') as f:
                reader = csv.reader(f)
                rows = list(reader)

        rows = list(reader) if isinstance(file_path_or_bytes, (bytes, bytearray)) else rows
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
        return pages

class PresentationExtractor:
    """Extracts slide text and structure from PPTX presentation files using standard library zipfile."""
    @staticmethod
    def extract(file_path_or_bytes) -> List[Dict[str, Any]]:
        if isinstance(file_path_or_bytes, (bytes, bytearray)):
            zf = zipfile.ZipFile(io.BytesIO(file_path_or_bytes))
        else:
            zf = zipfile.ZipFile(file_path_or_bytes)

        slide_names = [name for name in zf.namelist() if re.match(r'ppt/slides/slide\d+\.xml', name)]
        slide_names.sort(key=lambda x: int(re.search(r'\d+', x).group(0)) if re.search(r'\d+', x) else 0)

        if not slide_names:
            return [{
                'page_number': 1,
                'text': '',
                'confidence': 1.0,
                'words_count': 0,
                'width': 960.0,
                'height': 540.0,
                'extraction_type': 'pptx_extract',
                'engine': 'zipfile_xml',
                'engine_version': '1.0',
                'is_repaired': False,
                'bounding_boxes': []
            }]

        pages = []
        for idx, sname in enumerate(slide_names, 1):
            xml_data = zf.read(sname)
            root = ET.fromstring(xml_data)
            texts = [node.text for node in root.iter() if node.tag.endswith('}t') and node.text]
            slide_text = "\n".join(texts).strip()
            pages.append({
                'page_number': idx,
                'text': f"## Slide {idx}\n\n{slide_text}" if slide_text else f"## Slide {idx}\n\n[Empty slide]",
                'confidence': 1.0,
                'words_count': len(slide_text.split()),
                'width': 960.0,
                'height': 540.0,
                'extraction_type': 'pptx_extract',
                'engine': 'zipfile_xml',
                'engine_version': '1.0',
                'is_repaired': False,
                'bounding_boxes': []
            })
        return pages

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
    def __init__(self, ocr_provider: BaseOCRProvider = None):
        self.router = OCRRouter(ocr_provider=ocr_provider)

    def extract_document(self, file_path_or_bytes, doc_type: str, filename: str = '') -> List[Dict[str, Any]]:
        ext = os.path.splitext(filename.lower())[1] if filename else ''

        if doc_type == 'pdf' or ext == '.pdf':
            return self.router.process_pdf(file_path_or_bytes)
        elif doc_type == 'image' or ext in ('.png', '.jpg', '.jpeg'):
            return self.router.process_image(file_path_or_bytes)
        elif doc_type == 'docx' or ext == '.docx':
            return DocxExtractor.extract(file_path_or_bytes)
        elif ext == '.csv':
            return SpreadsheetExtractor.extract_csv(file_path_or_bytes)
        elif doc_type == 'spreadsheet' or ext in ('.xlsx', '.xls'):
            return SpreadsheetExtractor.extract_xlsx(file_path_or_bytes)
        elif doc_type == 'presentation' or ext in ('.pptx', '.ppt'):
            return PresentationExtractor.extract(file_path_or_bytes)
        else:
            return TextExtractor.extract(file_path_or_bytes)
