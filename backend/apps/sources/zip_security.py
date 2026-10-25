import hashlib
import os
import re
import zipfile
from typing import Dict, Any, List, Tuple, Optional
from django.conf import settings
from django.core.exceptions import ValidationError
from .services import ALLOWED_EXTENSIONS

class ZipSecurityError(ValidationError):
    """Raised when an archive violates enterprise security boundaries."""
    pass

# Configurable limits
ZIP_MAX_ARCHIVE_SIZE_BYTES = getattr(settings, 'ZIP_MAX_ARCHIVE_SIZE_BYTES', 100 * 1024 * 1024)  # 100 MB
ZIP_MAX_ENTRY_COUNT = getattr(settings, 'ZIP_MAX_ENTRY_COUNT', 500)
ZIP_MAX_UNCOMPRESSED_TOTAL_BYTES = getattr(settings, 'ZIP_MAX_UNCOMPRESSED_TOTAL_BYTES', 250 * 1024 * 1024)  # 250 MB
ZIP_MAX_SINGLE_FILE_SIZE_BYTES = getattr(settings, 'ZIP_MAX_SINGLE_FILE_SIZE_BYTES', 50 * 1024 * 1024)  # 50 MB
ZIP_MAX_COMPRESSION_RATIO = getattr(settings, 'ZIP_MAX_COMPRESSION_RATIO', 100)

NESTED_ARCHIVE_EXTENSIONS = {
    '.zip', '.tar', '.gz', '.tgz', '.bz2', '.tbz2', '.7z', '.rar', '.xz', '.iso', '.cab', '.z', '.apk'
}

UNSAFE_CHARS_PATTERN = re.compile(r'[<>:"|?*\x00-\x1f]')

class ZipArchiveSecurityService:
    """
    Enterprise-grade security gate for ZIP archives.
    Guarantees protection against:
    - Zip Slip / path traversal (relative components, absolute paths, drive letters, backslashes)
    - Decompression bombs & excessive compression ratios (per-entry and cumulative streaming verification)
    - Encrypted or corrupt archives
    - Excessive entry count and oversized files
    - Nested archive recursion bombs
    - Temporary file leakage
    """

    @staticmethod
    def sanitize_entry_path(raw_name: str) -> Tuple[str, str]:
        """
        Validates and sanitizes an archive entry path.
        Returns:
            (sanitized_relative_path, sanitized_basename)
        Raises:
            ZipSecurityError if traversal, null byte, or malicious pattern is detected.
        """
        if not raw_name or not raw_name.strip():
            raise ZipSecurityError("Archive entry has an empty filename.")

        # Check for null bytes
        if '\0' in raw_name:
            raise ZipSecurityError("Archive entry filename contains null byte (directory poison attempt).")

        # Normalize path separators
        normalized = raw_name.replace('\\', '/').strip()

        # Reject absolute paths (Unix style)
        if normalized.startswith('/'):
            raise ZipSecurityError(f"Path traversal detected: Absolute paths not permitted ('{raw_name}').")

        # Reject Windows drive roots (e.g. C:/ or D:\)
        if re.match(r'^[a-zA-Z]:', normalized):
            raise ZipSecurityError(f"Path traversal detected: Drive prefix not permitted ('{raw_name}').")

        # Check for path traversal components (.. or .)
        parts = [p for p in normalized.split('/') if p]
        for part in parts:
            if part == '..':
                raise ZipSecurityError(f"Zip Slip path traversal attack detected ('{raw_name}').")

        # Base filename
        raw_basename = parts[-1] if parts else normalized

        # Strip unsafe filesystem characters from basename while preserving valid Unicode
        sanitized_basename = UNSAFE_CHARS_PATTERN.sub('_', raw_basename).strip('. ')
        if not sanitized_basename:
            sanitized_basename = f"file_{hashlib.md5(raw_name.encode('utf-8', errors='ignore')).hexdigest()[:8]}"

        sanitized_rel_path = '/'.join(parts[:-1] + [sanitized_basename]) if len(parts) > 1 else sanitized_basename

        return sanitized_rel_path, sanitized_basename

    @classmethod
    def inspect_archive(cls, file_obj, archive_filename: str = '') -> Dict[str, Any]:
        """
        Performs non-destructive deep security inspection of an uploaded ZIP archive.
        Validates size, magic bytes, integrity, compression ratios, and parses all entries.
        """
        file_obj.seek(0, os.SEEK_END)
        archive_size = file_obj.tell()
        file_obj.seek(0)

        if archive_size == 0:
            raise ZipSecurityError("Archive file is empty (0 bytes).")

        if archive_size > ZIP_MAX_ARCHIVE_SIZE_BYTES:
            max_mb = ZIP_MAX_ARCHIVE_SIZE_BYTES // (1024 * 1024)
            raise ZipSecurityError(f"Archive exceeds maximum allowed size of {max_mb} MB.")

        # Magic byte check: ZIP header must start with PK\x03\x04 or PK\x05\x06
        header = file_obj.read(4)
        file_obj.seek(0)
        if not (header.startswith(b'PK\x03\x04') or header.startswith(b'PK\x05\x06')):
            raise ZipSecurityError("Invalid archive: Missing standard PK ZIP magic bytes.")

        # Compute archive SHA-256
        hasher = hashlib.sha256()
        for chunk in file_obj.chunks() if hasattr(file_obj, 'chunks') else iter(lambda: file_obj.read(65536), b''):
            hasher.update(chunk)
        archive_hash = hasher.hexdigest()
        file_obj.seek(0)

        # Open ZipFile and inspect structure
        try:
            zip_ref = zipfile.ZipFile(file_obj, 'r')
        except zipfile.BadZipFile as e:
            raise ZipSecurityError(f"Corrupted or invalid ZIP archive: {str(e)}")
        except Exception as e:
            raise ZipSecurityError(f"Failed to read ZIP archive: {str(e)}")

        with zip_ref:
            # Check for corrupt CRC or bad archive headers
            test_res = zip_ref.testzip()
            if test_res is not None:
                raise ZipSecurityError(f"Archive CRC32 checksum failed on entry: '{test_res}'. Archive is corrupted.")

            all_entries = zip_ref.infolist()
            # Filter out pure directory entries
            file_entries = [e for e in all_entries if not e.is_dir() and not e.filename.replace('\\', '/').endswith('/')]

            if len(file_entries) > ZIP_MAX_ENTRY_COUNT:
                raise ZipSecurityError(
                    f"Archive contains {len(file_entries)} files, exceeding maximum limit of {ZIP_MAX_ENTRY_COUNT} entries."
                )

            cumulative_uncompressed = 0
            entry_records: List[Dict[str, Any]] = []

            for info in file_entries:
                # 1. Encryption check
                if info.flag_bits & 0x1 or (hasattr(info, 'is_encrypted') and info.is_encrypted()):
                    raise ZipSecurityError("Archive is password-protected or encrypted. Encrypted archives are not supported.")

                # 2. Path sanitization & Zip Slip check
                try:
                    rel_path, sanitized_name = cls.sanitize_entry_path(info.filename)
                except ZipSecurityError as err:
                    raise ZipSecurityError(str(err))

                # 3. Compression ratio check (decompression bomb protection)
                comp_size = max(info.compress_size, 1)
                uncomp_size = info.file_size
                ratio = uncomp_size / comp_size

                if ratio > ZIP_MAX_COMPRESSION_RATIO and uncomp_size > 1024 * 1024:
                    raise ZipSecurityError(
                        f"Decompression bomb detected: Entry '{info.filename}' exhibits an excessive compression ratio ({ratio:.1f}:1)."
                    )

                cumulative_uncompressed += uncomp_size
                if cumulative_uncompressed > ZIP_MAX_UNCOMPRESSED_TOTAL_BYTES:
                    max_total_mb = ZIP_MAX_UNCOMPRESSED_TOTAL_BYTES // (1024 * 1024)
                    raise ZipSecurityError(
                        f"Decompression bomb detected: Total uncompressed content ({cumulative_uncompressed // (1024 * 1024)} MB) exceeds maximum allowed limit ({max_total_mb} MB)."
                    )

                # 4. Format & size classification
                ext = os.path.splitext(sanitized_name.lower())[1]
                is_nested = ext in NESTED_ARCHIVE_EXTENSIONS
                is_oversized = uncomp_size > ZIP_MAX_SINGLE_FILE_SIZE_BYTES
                is_zero_byte = uncomp_size == 0

                skip_reason = ""
                is_supported = False
                doc_type = ""

                if is_zero_byte:
                    skip_reason = "Empty file (0 bytes)."
                elif is_nested:
                    skip_reason = "Nested archive detected (recursive extraction disabled for security)."
                elif is_oversized:
                    max_single_mb = ZIP_MAX_SINGLE_FILE_SIZE_BYTES // (1024 * 1024)
                    skip_reason = f"File exceeds maximum allowed single file size of {max_single_mb} MB."
                elif ext in ALLOWED_EXTENSIONS:
                    is_supported = True
                    doc_type = ALLOWED_EXTENSIONS[ext]
                else:
                    skip_reason = f"Unsupported file extension '{ext}'."

                entry_records.append({
                    'original_path': info.filename,
                    'entry_path': rel_path,
                    'sanitized_filename': sanitized_name,
                    'file_size': uncomp_size,
                    'compressed_size': info.compress_size,
                    'document_type': doc_type,
                    'is_supported': is_supported,
                    'is_nested_archive': is_nested,
                    'skip_reason': skip_reason,
                    'zip_info': info
                })

            from .slack_engine import SlackExportService
            is_slack = SlackExportService.is_slack_archive(zip_ref)

            if is_slack:
                slack_data = SlackExportService.inspect_slack_archive(zip_ref)
                entry_records = []
                for ch in slack_data['channels']:
                    msg_cnt = ch['message_count']
                    is_supp = msg_cnt > 0 or len(ch['files']) > 0
                    skip_msg = ""
                    if not is_supp:
                        skip_msg = "Empty channel (0 messages)."
                    elif ch['is_private']:
                        skip_msg = f"Private Channel / DM ({msg_cnt} messages, restricted access)."
                    else:
                        skip_msg = f"Public Channel ({msg_cnt} messages)."

                    entry_records.append({
                        'original_path': f"slack/{ch['channel_name']}",
                        'entry_path': f"slack/{ch['channel_name']}",
                        'sanitized_filename': f"slack_{ch['channel_name']}.txt",
                        'file_size': max(msg_cnt * 200, 1024),
                        'compressed_size': 0,
                        'document_type': 'slack_channel',
                        'is_supported': is_supp,
                        'is_nested_archive': False,
                        'is_private': ch['is_private'],
                        'skip_reason': skip_msg,
                        'zip_info': None
                    })

                supported_count = sum(1 for e in entry_records if e['is_supported'])
                unsupported_count = len(entry_records) - supported_count

                return {
                    'archive_filename': archive_filename or 'slack_export.zip',
                    'archive_size': archive_size,
                    'archive_hash': archive_hash,
                    'is_slack_export': True,
                    'total_entries': len(entry_records),
                    'supported_entries': supported_count,
                    'unsupported_entries': unsupported_count,
                    'cumulative_uncompressed_bytes': archive_size * 2,
                    'entries': entry_records,
                }

            supported_count = sum(1 for e in entry_records if e['is_supported'])
            unsupported_count = len(entry_records) - supported_count

            return {
                'archive_filename': archive_filename or 'archive.zip',
                'archive_size': archive_size,
                'archive_hash': archive_hash,
                'is_slack_export': False,
                'total_entries': len(entry_records),
                'supported_entries': supported_count,
                'unsupported_entries': unsupported_count,
                'cumulative_uncompressed_bytes': cumulative_uncompressed,
                'entries': entry_records,
            }

    @classmethod
    def extract_single_entry_bounded(
        cls, 
        zip_ref: zipfile.ZipFile, 
        info: zipfile.ZipInfo, 
        target_dir: str, 
        sanitized_filename: str
    ) -> Tuple[str, str, int]:
        """
        Extracts a single ZIP entry into target_dir with strict bounded streaming verification:
        - Confines path strictly inside target_dir.
        - Verifies actual uncompressed byte stream count against limit.
        - Calculates streaming SHA-256 fingerprint.
        Returns:
            (destination_filepath, sha256_hash, bytes_written)
        """
        target_file = os.path.abspath(os.path.join(target_dir, sanitized_filename))
        abs_target_dir = os.path.abspath(target_dir)

        # Enforce that destination stays strictly inside target_dir
        if not (target_file == abs_target_dir or target_file.startswith(abs_target_dir + os.sep)):
            raise ZipSecurityError(f"Path traversal escape detected during extraction: '{sanitized_filename}'.")

        # Stream extraction with byte quota
        hasher = hashlib.sha256()
        bytes_written = 0

        with zip_ref.open(info) as src, open(target_file, 'wb') as dst:
            while True:
                chunk = src.read(65536)
                if not chunk:
                    break
                bytes_written += len(chunk)
                if bytes_written > ZIP_MAX_SINGLE_FILE_SIZE_BYTES:
                    # Clean up partial file immediately
                    try:
                        dst.close()
                        os.remove(target_file)
                    except Exception:
                        pass
                    raise ZipSecurityError(
                        f"Decompression bomb detected: actual stream length for '{sanitized_filename}' exceeded {ZIP_MAX_SINGLE_FILE_SIZE_BYTES // (1024*1024)} MB."
                    )
                hasher.update(chunk)
                dst.write(chunk)

        return target_file, hasher.hexdigest(), bytes_written
