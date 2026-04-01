import os
from cryptography.fernet import Fernet, InvalidToken


def _get_fernet() -> Fernet:
    key = os.getenv("ENCRYPTION_KEY")
    if not key:
        raise RuntimeError(
            "ENCRYPTION_KEY is not set in environment. "
            "Generate one with: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
        )
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
