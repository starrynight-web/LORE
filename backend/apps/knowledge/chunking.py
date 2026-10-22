import re
from typing import List, Dict, Any

class StructureAwareChunker:
    """
    Structure-aware document chunker:
    - Page-aware for PDFs/OCR scans.
    - Heading-aware for Markdown and prose.
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
        pages_data: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        chunks = []
        global_chunk_idx = 0

        for page in pages_data:
            page_num = page.get('page_number', 1)
            text = page.get('text', '').strip()
            if not text:
                continue

            # Split page into sections by headings if present
            sections = cls._split_into_sections(text)

            for sec_heading, sec_text in sections:
                if not sec_text.strip():
                    continue
                words = sec_text.split()
                if not words:
                    continue
                if len(words) <= cls.TARGET_CHUNK_TOKENS:
                    header = cls._build_contextual_header(
                        doc_title=doc_title,
                        org_name=org_name,
                        ws_name=ws_name,
                        page_num=page_num,
                        heading_path=sec_heading,
                        authority_rank=authority_rank
                    )
                    chunks.append({
                        'chunk_index': global_chunk_idx,
                        'text': sec_text,
                        'contextual_header': header,
                        'page_number': page_num,
                        'heading_path': sec_heading,
                        'token_count': len(words),
                        'char_offset_start': 0,
                        'char_offset_end': len(sec_text),
                    })
                    global_chunk_idx += 1
                else:
                    # Break long section into overlapping window chunks
                    step = cls.TARGET_CHUNK_TOKENS - cls.OVERLAP_TOKENS
                    for i in range(0, len(words), step):
                        chunk_words = words[i:i + cls.TARGET_CHUNK_TOKENS]
                        chunk_str = " ".join(chunk_words)
                        header = cls._build_contextual_header(
                            doc_title=doc_title,
                            org_name=org_name,
                            ws_name=ws_name,
                            page_num=page_num,
                            heading_path=sec_heading,
                            authority_rank=authority_rank
                        )
                        chunks.append({
                            'chunk_index': global_chunk_idx,
                            'text': chunk_str,
                            'contextual_header': header,
                            'page_number': page_num,
                            'heading_path': sec_heading,
                            'token_count': len(chunk_words),
                            'char_offset_start': 0,
                            'char_offset_end': len(chunk_str),
                        })
                        global_chunk_idx += 1
                        if i + cls.TARGET_CHUNK_TOKENS >= len(words):
                            break

        return chunks

    @staticmethod
    def _split_into_sections(text: str) -> List[tuple]:
        """Splits text on Markdown headings or returns as a single section."""
        lines = text.split('\n')
        sections = []
        current_heading = "General"
        current_lines = []

        for line in lines:
            h_match = re.match(r'^(#{1,4})\s+(.+)', line)
            if h_match:
                if current_lines:
                    sections.append((current_heading, "\n".join(current_lines).strip()))
                    current_lines = []
                current_heading = h_match.group(2).strip()
            else:
                current_lines.append(line)

        if current_lines:
            sections.append((current_heading, "\n".join(current_lines).strip()))

        return sections if sections else [("General", text)]

    @staticmethod
    def _build_contextual_header(
        doc_title: str,
        org_name: str,
        ws_name: str,
        page_num: int,
        heading_path: str,
        authority_rank: int
    ) -> str:
        """Anthropic Contextual RAG header prepended before embedding."""
        return (
            f"Document: {doc_title} | Workspace: {ws_name} | "
            f"Page: {page_num} | Section: {heading_path} | Authority Rank: {authority_rank}"
        )
