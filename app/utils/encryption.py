import os
from cryptography.fernet import Fernet, InvalidToken


def _get_fernet() -> Fernet:
    key = os.getenv("ENCRYPTION_KEY")
    if not key:
        print("[LEVIX WARNING] ENCRYPTION_KEY not set. Using a temporary fallback key (Encryption will NOT be persistent!)")
        # Temporary fallback key for non-crashing startup
        key = "temporary_insecure_fallback_key_for_startup_only"
        # Return a valid key format for Fernet
        import base64
        key = base64.urlsafe_b64encode(key.ljust(32)[:32].encode()).decode()
    return Fernet(key.encode() if isinstance(key, str) else key)


def encrypt(text: str) -> str:
    """Encrypt a plaintext string and return a base64-encoded ciphertext string.

    Idempotent: if the value is already a Fernet token (starts with 'gAAAA'),
    it is returned as-is to prevent double encryption.
    """
    if not text:
        return text
    if text.startswith("gAAAA"):
        return text  # already encrypted — skip
    f = _get_fernet()
    return f.encrypt(text.encode()).decode()


def decrypt(token: str) -> str | None:
    """Decrypt a Fernet token and return the plaintext string.

    Returns None (and logs) if decryption fails — never raises.
    """
    if not token:
        return None
    try:
        f = _get_fernet()
        return f.decrypt(token.encode()).decode()
    except (InvalidToken, Exception) as e:
        print(f"[Encryption] Failed to decrypt token: {type(e).__name__}: {e}")
        return None
