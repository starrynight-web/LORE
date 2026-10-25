import base64
import hashlib
import logging
from django.conf import settings
from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger(__name__)


class TokenEncryptionService:
    """
    Enterprise-grade AES-128-CBC + HMAC-SHA256 authenticated encryption service
    for OAuth tokens (access tokens, refresh tokens, credentials).
    Ensures secrets are NEVER persisted in plaintext in the database or serialized in logs.
    """

    @classmethod
    def _get_fernet_key(cls) -> bytes:
        # Check explicit encryption key in settings, or derive deterministically from SECRET_KEY
        explicit_key = getattr(settings, 'CONNECTOR_ENCRYPTION_KEY', None)
        if explicit_key:
            if isinstance(explicit_key, str):
                explicit_key = explicit_key.encode('utf-8')
            # If already valid 32-byte urlsafe base64
            try:
                if len(base64.urlsafe_b64decode(explicit_key)) == 32:
                    return explicit_key
            except Exception:
                pass
            return base64.urlsafe_b64encode(hashlib.sha256(explicit_key).digest())

        secret_bytes = settings.SECRET_KEY.encode('utf-8')
        derived_32 = hashlib.sha256(b"lore-email-connector-tokens:" + secret_bytes).digest()
        return base64.urlsafe_b64encode(derived_32)

    @classmethod
    def encrypt(cls, plaintext: str) -> str:
        """Encrypts plaintext string into an authenticated Fernet ciphertext string."""
        if not plaintext:
            return ""
        key = cls._get_fernet_key()
        f = Fernet(key)
        encrypted_bytes = f.encrypt(plaintext.encode('utf-8'))
        return encrypted_bytes.decode('utf-8')

    @classmethod
    def decrypt(cls, ciphertext: str) -> str:
        """Decrypts authenticated Fernet ciphertext into plaintext string."""
        if not ciphertext:
            return ""
        key = cls._get_fernet_key()
        f = Fernet(key)
        try:
            decrypted_bytes = f.decrypt(ciphertext.encode('utf-8'))
            return decrypted_bytes.decode('utf-8')
        except (InvalidToken, Exception) as e:
            logger.error("Failed to decrypt stored OAuth token: %s", type(e).__name__)
            return ""


# Module-level convenience aliases
encrypt_token = TokenEncryptionService.encrypt
decrypt_token = TokenEncryptionService.decrypt
