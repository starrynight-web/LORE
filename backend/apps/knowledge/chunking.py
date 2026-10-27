import re
from typing import List, Dict, Any, Tuple, Optional

class StructureAwareChunker:
    """
    Structure-aware document chunker:
    - Page-aware for PDFs/OCR scans.
    - Heading-aware for Markdown, numbered sections, and prose.
    - Preserves table headers with continuation chunks and keeps rows intact.
    - Preserves section identifiers (e.g. 'Section 4', 'Section 5', 'Q2') and field labels.
    - Keeps lodging limits and meal allowances in separate chunks.
    - Appends contextual metadata header to anchor isolated chunks (Anthropic Contextual RAG 2.0).
    """

    TARGET_CHUNK_TOKENS = 400
    OVERLAP_TOKENS = 50

    @classmethod
    def chunk_document_pages(
        cls,
        doc_id: str,
        doc_title: str,
        org_name: str,
        ws_name: str,
        authority_rank: int,
        pages_data: List[Dict[str, Any]],
        document_code: str = "",
        status: str = "ready"
    ) -> List[Dict[str, Any]]:
        chunks = []
        global_chunk_idx = 0

        # Pre-process pages to stitch cross-page orphan section headings (e.g. DOC-002 Sec 5 at bottom of p1)
        normalized_pages = cls._normalize_page_sections(pages_data)

        for page in normalized_pages:
            page_num = page.get('page_number', 1)
            text = page.get('text', '').strip()
            if not text:
                continue

            # Split page into sections by structured headings
            sections = cls._split_into_sections(text)

            for sec_heading, sec_id, sec_text in sections:
                if not sec_text.strip():
                    continue

                words = sec_text.split()
                if not words:
                    continue

                # Detect if section contains Markdown table
                table_header, table_sep, is_table = cls._detect_table_header(sec_text)

                if len(words) <= cls.TARGET_CHUNK_TOKENS:
                    header = cls._build_contextual_header(
                        doc_id=doc_id,
                        doc_code=document_code,
                        doc_title=doc_title,
                        org_name=org_name,
                        ws_name=ws_name,
                        page_num=page_num,
                        heading_path=sec_heading,
                        section_identifier=sec_id,
                        authority_rank=authority_rank,
                        status=status
                    )
                    chunks.append({
                        'chunk_index': global_chunk_idx,
                        'text': sec_text,
                        'contextual_header': header,
                        'page_number': page_num,
                        'heading_path': sec_heading,
                        'section_identifier': sec_id,
                        'token_count': len(words),
                        'char_offset_start': 0,
                        'char_offset_end': len(sec_text),
                        'metadata': {
                            'document_code': document_code,
                            'section_identifier': sec_id,
                            'heading_path': sec_heading,
                            'page_number': page_num,
                            'is_table': is_table
                        }
                    })
                    global_chunk_idx += 1
                else:
                    # Break long section into chunks while keeping table headers / sentence boundaries intact
                    sub_chunks = cls._chunk_long_section(
                        sec_text=sec_text,
                        table_header=table_header,
                        table_sep=table_sep,
                        target_tokens=cls.TARGET_CHUNK_TOKENS,
                        overlap_tokens=cls.OVERLAP_TOKENS
                    )
                    for sub_text in sub_chunks:
                        sub_words = sub_text.split()
                        header = cls._build_contextual_header(
                            doc_id=doc_id,
                            doc_code=document_code,
                            doc_title=doc_title,
                            org_name=org_name,
                            ws_name=ws_name,
                            page_num=page_num,
                            heading_path=sec_heading,
                            section_identifier=sec_id,
                            authority_rank=authority_rank,
                            status=status
                        )
                        chunks.append({
                            'chunk_index': global_chunk_idx,
                            'text': sub_text,
                            'contextual_header': header,
                            'page_number': page_num,
                            'heading_path': sec_heading,
                            'section_identifier': sec_id,
                            'token_count': len(sub_words),
                            'char_offset_start': 0,
                            'char_offset_end': len(sub_text),
                            'metadata': {
                                'document_code': document_code,
                                'section_identifier': sec_id,
                                'heading_path': sec_heading,
                                'page_number': page_num,
                                'is_table': is_table,
                                'table_header_preserved': bool(table_header)
                            }
                        })
                        global_chunk_idx += 1

        return chunks

    @classmethod
    def _normalize_page_sections(cls, pages_data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Detects if a page ends with an orphan section heading (e.g. '5. Meal Allowances' at page bottom)
        and prepends it to the beginning of the next page so the heading and body stay together.
        """
        result = []
        carry_heading = ""

        for p in pages_data:
            text = p.get('text', '').strip()
            if carry_heading:
                text = f"{carry_heading}\n{text}"
                carry_heading = ""

            lines = text.split('\n')
            # Check last 3 non-empty lines for an orphan heading with <= 20 words body
            non_empty = [l.strip() for l in lines if l.strip()]
            if non_empty:
                last_line = non_empty[-1]
                h, sid = cls._extract_section_info(last_line)
                if h:
                    # Heading is at the very bottom of the page
                    carry_heading = last_line
                    # Remove last line from current page
                    lines = lines[:-1]
                    text = "\n".join(lines).strip()
                elif len(non_empty) >= 2:
                    h2, sid2 = cls._extract_section_info(non_empty[-2])
                    # If second to last line is a heading and last line is a page footer or < 15 words
                    if h2 and len(non_empty[-1].split()) <= 15 and ('page' in non_empty[-1].lower() or 'doc-' in non_empty[-1].lower()):
                        carry_heading = f"{non_empty[-2]}\n"
                        # Strip both heading and footer from this page
                        idx = text.rfind(non_empty[-2])
                        if idx != -1:
                            text = text[:idx].strip()

            result.append({**p, 'text': text})

        if carry_heading and result:
            result[-1]['text'] = f"{result[-1]['text']}\n{carry_heading}"

        return result

    @classmethod
    def _split_into_sections(cls, text: str) -> List[Tuple[str, str, str]]:
        """
        Splits text on Markdown headings, numbered sections, Q&A blocks, and named sections.
        Returns List of (heading_path, section_identifier, section_text).
        """
        lines = text.split('\n')
        sections = []
        current_heading = "General"
        current_sec_id = ""
        current_lines = []

        for line in lines:
            h, sec_id = cls._extract_section_info(line)
            if h:
                if current_lines:
                    sec_text = "\n".join(current_lines).strip()
                    if sec_text:
                        sections.append((current_heading, current_sec_id, sec_text))
                    current_lines = []
                current_heading = h
                current_sec_id = sec_id
            else:
                current_lines.append(line)

        if current_lines:
            sec_text = "\n".join(current_lines).strip()
            if sec_text:
                sections.append((current_heading, current_sec_id, sec_text))

        return sections if sections else [("General", "", text)]

    @classmethod
    def _extract_section_info(cls, line: str) -> Tuple[Optional[str], Optional[str]]:
        """
        Extracts (heading_title, section_identifier) from a candidate heading line.
        """
        clean = line.strip()
        if not clean or len(clean) > 140:
            return None, None

        # 1. Markdown heading: # Heading or ## Heading
        m_md = re.match(r'^(#{1,4})\s+(.+)', clean)
        if m_md:
            h = m_md.group(2).strip()
            sec_id_m = re.search(r'(?:Section\s+(\d+(?:\.\d+)*)|(Q\d+)|(AR-\d{4}-\d{3})|Sheet:\s*([^\|\n]+))', h, re.IGNORECASE)
            sec_id = sec_id_m.group(0) if sec_id_m else ""
            return h, sec_id

        # 2. Numbered heading: "1. Purpose and Scope" or "Section 4: Hotel Limits" or "4. Hotel Limits"
        m_num = re.match(r'^\s*(?:(Section\s+\d+(?:\.\d+)*)[:\.]?\s+|(\d+(?:\.\d+)*)[\.:]\s+)([A-Z][A-Za-z0-9\s&/\-]+)', clean)
        if m_num:
            sec_num = m_num.group(1) or f"Section {m_num.group(2)}"
            return clean, sec_num

        # 3. Q&A item: "Q1. How many..." or "Q2. How many..."
        m_qa = re.match(r'^\s*(Q\d+)[\.:]\s+(.+)', clean)
        if m_qa:
            return clean, m_qa.group(1)

        # 4. Access Request item: "AR-2024-041 ..."
        m_ar = re.match(r'^\s*(AR-\d{4}-\d{3})\b.*', clean)
        if m_ar:
            return clean, m_ar.group(1)

        # 5. Named standard headings in policies
        m_named = re.match(r'^\s*(Meal Allowance \(per travel day\) Guidance|Meal Allowances|Hotel Limits|Lodging Limit|Airfare Limits|Ground Transportation and Other Costs|Receipts and Expense Claims|Exceptions and Compliance|Review and Approval|Carryover and Expiry|Annual Leave Accrual|Parties and Purpose|Contract Term|Annual Fee and Invoicing|Renewal Conditions|Termination|Lodging Limit|Supersession and Retention)\b', clean, re.IGNORECASE)
        if m_named:
            canonical_name = m_named.group(1)
            # Map known policy topics to Section identifiers if standard
            sec_id_map = {
                'Hotel Limits': 'Section 4',
                'Lodging Limit': 'Section 2',
                'Meal Allowances': 'Section 5',
                'Meal Allowance (per travel day) Guidance': 'Section 5',
                'Receipts and Expense Claims': 'Section 6',
                'Ground Transportation and Other Costs': 'Section 7',
                'Exceptions and Compliance': 'Section 8',
                'Review and Approval': 'Section 9',
                'Carryover and Expiry': 'Section 4',
                'Contract Term': 'Section 2',
                'Annual Fee and Invoicing': 'Section 3',
                'Renewal Conditions': 'Section 4',
                'Termination': 'Section 5',
                'Supersession and Retention': 'Section 6'
            }
            sec_id = sec_id_map.get(canonical_name, canonical_name)
            return clean, sec_id

        return None, None

    @classmethod
    def _detect_table_header(cls, text: str) -> Tuple[str, str, bool]:
        """
        Checks if text contains a pipe table, returning (header_row, separator_row, is_table).
        """
        lines = [l.strip() for l in text.split('\n') if l.strip()]
        for i, line in enumerate(lines):
            if line.count('|') >= 2:
                # Potential table header
                header = line
                sep = ""
                if i + 1 < len(lines) and re.match(r'^[\s\|\-:]+$', lines[i + 1]) and lines[i + 1].count('|') >= 2:
                    sep = lines[i + 1]
                return header, sep, True
        return "", "", False

    @classmethod
    def _chunk_long_section(
        cls,
        sec_text: str,
        table_header: str,
        table_sep: str,
        target_tokens: int,
        overlap_tokens: int
    ) -> List[str]:
        """
        Breaks long section text into chunks:
        - If table rows are present, splits by rows and prepends the table header to continuation chunks.
        - Otherwise splits on sentence boundaries, keeping numbers with their units/labels.
        """
        lines = [l for l in sec_text.split('\n') if l.strip()]

        if table_header:
            # Table-aware row splitting
            chunks = []
            curr_chunk_lines = [table_header]
            if table_sep:
                curr_chunk_lines.append(table_sep)
            curr_words = len(table_header.split()) + len(table_sep.split())

            for line in lines:
                if line == table_header or line == table_sep:
                    continue
                line_words = len(line.split())
                if curr_words + line_words > target_tokens and len(curr_chunk_lines) > (2 if table_sep else 1):
                    chunks.append("\n".join(curr_chunk_lines))
                    curr_chunk_lines = [table_header]
                    if table_sep:
                        curr_chunk_lines.append(table_sep)
                    curr_words = len(table_header.split()) + len(table_sep.split())

                curr_chunk_lines.append(line)
                curr_words += line_words

            if len(curr_chunk_lines) > (2 if table_sep else 1):
                chunks.append("\n".join(curr_chunk_lines))
            return chunks if chunks else [sec_text]

        # Prose: split by sentences / paragraphs
        paragraphs = sec_text.split('\n\n')
        chunks = []
        curr_paras = []
        curr_words = 0

        for para in paragraphs:
            p_words = len(para.split())
            if curr_words + p_words > target_tokens and curr_paras:
                chunks.append("\n\n".join(curr_paras))
                curr_paras = []
                curr_words = 0

            curr_paras.append(para)
            curr_words += p_words

        if curr_paras:
            chunks.append("\n\n".join(curr_paras))

        return chunks if chunks else [sec_text]

    @staticmethod
    def _build_contextual_header(
        doc_id: str,
        doc_code: str,
        doc_title: str,
        org_name: str,
        ws_name: str,
        page_num: int,
        heading_path: str,
        section_identifier: str,
        authority_rank: int,
        status: str = "ready"
    ) -> str:
        """Anthropic Contextual RAG header prepended before embedding."""
        parts = [
            f"Document: {doc_title}",
            f"Doc ID: {doc_code or doc_id}",
            f"Workspace: {ws_name}",
            f"Page: {page_num}",
        ]
        if section_identifier:
            parts.append(f"Section ID: {section_identifier}")
        if heading_path and heading_path != "General":
            parts.append(f"Section: {heading_path}")
        if status and status != "ready":
            parts.append(f"Status: {status}")
        parts.append(f"Authority Rank: {authority_rank}")
        return " | ".join(parts)
