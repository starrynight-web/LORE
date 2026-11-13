import hashlib
import os
from typing import Dict, Any, Tuple
from django.core.exceptions import ValidationError

MAX_FILE_SIZE_BYTES = 50 * 1024 * 1024  # 50 MB

ALLOWED_EXTENSIONS = {
    '.pdf': 'pdf',
    '.docx': 'docx',
    '.txt': 'txt',
    '.md': 'txt',
    '.markdown': 'txt',
    '.csv': 'spreadsheet',
    '.xlsx': 'spreadsheet',
    '.xls': 'spreadsheet',
    '.png': 'image',
    '.jpg': 'image',
    '.jpeg': 'image',
    '.tiff': 'image',
    '.tif': 'image',
    '.webp': 'image',
    '.pptx': 'presentation',
    '.ppt': 'presentation',
    '.html': 'txt',
    '.htm': 'txt',
    '.json': 'json',
}

class StorageSecurityService:
    """
    Validates uploaded files for enterprise security and provenance:
    - Enforces size limit (<= 50MB)
    - Verifies file magic bytes (never trusts client headers alone)
    - Computes cryptographic SHA-256 fingerprint
    """

    @staticmethod
    def inspect_and_validate(file_obj) -> Dict[str, Any]:
        size = file_obj.size
        if size == 0:
            raise ValidationError("File is empty (0 bytes). Cannot ingest empty content.")
        if size > MAX_FILE_SIZE_BYTES:
            raise ValidationError(f"File exceeds maximum allowed size of {MAX_FILE_SIZE_BYTES // (1024*1024)} MB.")

        name = file_obj.name.lower()
        ext = os.path.splitext(name)[1]
        if ext not in ALLOWED_EXTENSIONS:
            raise ValidationError(
                f"Unsupported file extension '{ext}'. Only formats with verified functioning parsers are accepted: {', '.join(sorted(ALLOWED_EXTENSIONS.keys()))}"
            )

        doc_type = ALLOWED_EXTENSIONS[ext]

        # Read first 2KB for magic byte analysis
        file_obj.seek(0)
        header = file_obj.read(2048)

        # Compute SHA-256 over entire file
        hasher = hashlib.sha256()
        file_obj.seek(0)
        for chunk in file_obj.chunks():
            hasher.update(chunk)
        sha256_hash = hasher.hexdigest()
        file_obj.seek(0)

        # Validate magic bytes against claimed type
        mime_type = 'application/octet-stream'

        if ext == '.pdf':
            if not header.startswith(b'%PDF'):
                raise ValidationError("Invalid PDF file: Missing %PDF magic bytes.")
            StorageSecurityService._inspect_pdf_active_content(file_obj)
            mime_type = 'application/pdf'

        elif ext == '.png':
            if not header.startswith(b'\x89PNG\r\n\x1a\n'):
                raise ValidationError("Invalid PNG file: Corrupted or missing PNG header.")
            mime_type = 'image/png'

        elif ext in ('.jpg', '.jpeg'):
            if not header.startswith(b'\xFF\xD8\xFF'):
                raise ValidationError("Invalid JPEG file: Corrupted or missing JPEG header.")
            mime_type = 'image/jpeg'

        elif ext in ('.tiff', '.tif'):
            if not (header.startswith(b'II*\x00') or header.startswith(b'MM\x00*')):
                raise ValidationError("Invalid TIFF file: Missing or corrupted TIFF header.")
            mime_type = 'image/tiff'

        elif ext == '.webp':
            if not (header.startswith(b'RIFF') and len(header) >= 12 and header[8:12] == b'WEBP'):
                raise ValidationError("Invalid WEBP file: Missing RIFF/WEBP header signature.")
            mime_type = 'image/webp'

        elif ext in ('.docx', '.xlsx', '.pptx'):
            # Modern Office files are PK zip archives
            if not header.startswith(b'PK\x03\x04'):
                raise ValidationError(f"Invalid Microsoft Office file '{ext}': Missing PK zip signature.")
            StorageSecurityService._inspect_ooxml_zip(file_obj, ext)
            if ext == '.docx':
                mime_type = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
            elif ext == '.xlsx':
                mime_type = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
            elif ext == '.pptx':
                mime_type = 'application/vnd.openxmlformats-officedocument.presentationml.presentation'

        elif ext in ('.ppt', '.xls'):
            # Compound File Binary Format or PK zip
            if not (header.startswith(b'\xD0\xCF\x11\xE0\xA1\xB1\x1A\xE1') or header.startswith(b'PK\x03\x04')):
                raise ValidationError(f"Invalid legacy Office file '{ext}': Missing binary OLE or PK signature.")
            mime_type = 'application/vnd.ms-powerpoint' if ext == '.ppt' else 'application/vnd.ms-excel'

        elif ext in ('.txt', '.md', '.markdown', '.csv', '.html', '.htm', '.json'):
            try:
                header.decode('utf-8')
                if ext in ('.html', '.htm'):
                    mime_type = 'text/html'
                elif ext == '.csv':
                    mime_type = 'text/csv'
                elif ext == '.json':
                    mime_type = 'application/json'
                else:
                    mime_type = 'text/plain'
            except UnicodeDecodeError:
                # Check for latin-1 or ASCII fallback
                try:
                    header.decode('latin-1')
                    if ext in ('.html', '.htm'):
                        mime_type = 'text/html'
                    elif ext == '.csv':
                        mime_type = 'text/csv'
                    elif ext == '.json':
                        mime_type = 'application/json'
                    else:
                        mime_type = 'text/plain'
                except Exception:
                    raise ValidationError("Text document contains invalid non-text binary data.")

        return {
            'document_type': doc_type,
            'mime_type': mime_type,
            'file_size': size,
            'file_hash': sha256_hash,
        }

    @staticmethod
    def _inspect_pdf_active_content(file_obj) -> None:
        """Rejects PDFs containing active /JavaScript, /JS actions, or /Launch actions without executing them."""
        import re
        pattern = re.compile(rb'/(?:JavaScript|Launch)\b|/JS\s*(?:\(|<<|[0-9]+\s+[0-9]+\s+R)')
        try:
            file_obj.seek(0)
            overlap = b''
            while True:
                chunk = file_obj.read(1024 * 1024)
                if not chunk:
                    break
                buf = overlap + chunk
                if pattern.search(buf):
                    raise ValidationError(
                        "Blocked PDF upload containing embedded active JavaScript or Launch actions."
                    )
                overlap = buf[-64:]
        finally:
            try:
                file_obj.seek(0)
            except Exception:
                pass

    @staticmethod
    def _inspect_ooxml_zip(file_obj, ext: str) -> None:
        """Inspects OOXML ZIP entries for path traversal, compression bombs, macros, and XML DTDs."""
        import zipfile
        import zlib
        max_entries = 5000
        max_single_bytes = 100 * 1024 * 1024
        max_total_bytes = 200 * 1024 * 1024
        bomb_ratio_threshold_bytes = 10 * 1024 * 1024
        max_ratio = 100.0
        try:
            file_obj.seek(0)
            with zipfile.ZipFile(file_obj, 'r') as zf:
                infos = zf.infolist()
                if len(infos) > max_entries:
                    raise ValidationError(
                        f"OOXML archive '{ext}' exceeds maximum entry count ({max_entries})."
                    )
                total_uncompressed = 0
                for info in infos:
                    normalized = info.filename.replace('\\', '/').lower()
                    if '..' in normalized.split('/') or normalized.startswith('/') or ':' in info.filename:
                        raise ValidationError(
                            f"Blocked OOXML archive '{ext}' with unsafe path entry: {info.filename}"
                        )
                    if (
                        normalized.endswith(('vbaproject.bin', 'vbadata.xml'))
                        or '/vbaproject' in normalized
                        or 'activex/' in normalized
                        or normalized.endswith(('.exe', '.dll', '.ps1', '.vbs', '.vbe', '.js', '.bat', '.cmd', '.scr'))
                    ):
                        raise ValidationError(
                            f"Blocked OOXML archive '{ext}' containing embedded macros or executable payload: {info.filename}"
                        )
                    if info.file_size > max_single_bytes:
                        raise ValidationError(
                            f"Blocked OOXML archive '{ext}': entry exceeds maximum uncompressed size limit."
                        )
                    total_uncompressed += max(0, info.file_size)
                    if total_uncompressed > max_total_bytes:
                        raise ValidationError(
                            f"Blocked OOXML archive '{ext}': total uncompressed size exceeds safe limit."
                        )
                    if info.file_size > bomb_ratio_threshold_bytes:
                        if info.compress_size <= 0 or (info.file_size / info.compress_size) > max_ratio:
                            raise ValidationError(
                                f"Blocked OOXML archive '{ext}': suspicious decompression ratio detected."
                            )
                    if normalized.endswith(('.xml', '.rels')) and info.file_size <= 5 * 1024 * 1024:
                        with zf.open(info, 'r') as entry_f:
                            head = entry_f.read(65536).lower()
                        if b'<!doctype' in head or b'<!entity' in head:
                            raise ValidationError(
                                f"Blocked OOXML archive '{ext}' containing unsafe XML DOCTYPE/ENTITY declaration."
                            )
        except ValidationError:
            raise
        except (zipfile.BadZipFile, NotImplementedError, zlib.error, ValueError):
            raise ValidationError(f"Invalid or corrupted Microsoft Office archive '{ext}'.")
        finally:
            try:
                file_obj.seek(0)
            except Exception:
                pass
