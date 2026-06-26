import hashlib
import secrets

API_KEY_PUBLIC_PREFIX = "vk_"
API_KEY_RANDOM_BYTES = 24
API_KEY_DISPLAY_PREFIX_LENGTH = 7


def generate_api_key() -> tuple[str, str, str]:
    """Generate a new API key.

    Returns (plaintext, display_prefix, sha256_hash).
    The plaintext is only ever returned here and to the user once.
    """
    random_part = secrets.token_urlsafe(API_KEY_RANDOM_BYTES)
    plaintext = f"{API_KEY_PUBLIC_PREFIX}{random_part}"
    display_prefix = plaintext[:API_KEY_DISPLAY_PREFIX_LENGTH]
    key_hash = hash_api_key(plaintext)
    return plaintext, display_prefix, key_hash


def hash_api_key(plaintext: str) -> str:
    return hashlib.sha256(plaintext.encode("utf-8")).hexdigest()
