"""
Credential storage with Fernet encryption.

Provides encrypt/decrypt utilities and CRUD operations for credentials.
"""

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session as DBSession

from app.config import settings
from app.models import Credential


class EncryptionError(Exception):
    """Raised when encryption/decryption fails."""

    pass


def _get_fernet() -> Fernet:
    """Get Fernet instance with configured key."""
    key = settings.agent_hub_encryption_key
    if not key:
        raise EncryptionError("AGENT_HUB_ENCRYPTION_KEY not configured")
    try:
        return Fernet(key.encode())
    except Exception as e:
        raise EncryptionError(f"Invalid encryption key: {e}") from e


def encrypt_value(plaintext: str) -> bytes:
    """Encrypt a plaintext string.

    Args:
        plaintext: The value to encrypt

    Returns:
        Encrypted bytes

    Raises:
        EncryptionError: If encryption fails
    """
    fernet = _get_fernet()
    return fernet.encrypt(plaintext.encode())


def decrypt_value(ciphertext: bytes) -> str:
    """Decrypt encrypted bytes.

    Args:
        ciphertext: The encrypted bytes

    Returns:
        Decrypted plaintext string

    Raises:
        EncryptionError: If decryption fails
    """
    fernet = _get_fernet()
    try:
        return fernet.decrypt(ciphertext).decode()
    except InvalidToken as e:
        raise EncryptionError("Decryption failed - invalid token or key") from e


def store_credential(
    db: DBSession,
    provider: str,
    credential_type: str,
    value: str,
) -> Credential:
    """Store an encrypted credential.

    Args:
        db: Database session
        provider: Provider name (claude, gemini)
        credential_type: Type of credential (api_key, oauth_token, etc.)
        value: Plaintext credential value

    Returns:
        Created Credential model
    """
    encrypted = encrypt_value(value)
    credential = Credential(
        provider=provider,
        credential_type=credential_type,
        value_encrypted=encrypted,
    )
    db.add(credential)
    db.commit()
    db.refresh(credential)
    return credential


def get_credential(
    db: DBSession,
    provider: str,
    credential_type: str,
) -> str | None:
    """Get a decrypted credential value.

    Args:
        db: Database session
        provider: Provider name
        credential_type: Type of credential

    Returns:
        Decrypted credential value, or None if not found
    """
    stmt = select(Credential).where(
        Credential.provider == provider,
        Credential.credential_type == credential_type,
    )
    credential = db.execute(stmt).scalar_one_or_none()
    if credential is None:
        return None
    return decrypt_value(credential.value_encrypted)


def get_credential_by_id(db: DBSession, credential_id: int) -> Credential | None:
    """Get credential by ID (without decrypting)."""
    return db.get(Credential, credential_id)


def update_credential(
    db: DBSession,
    credential_id: int,
    value: str,
) -> Credential | None:
    """Update an existing credential.

    Args:
        db: Database session
        credential_id: ID of credential to update
        value: New plaintext value

    Returns:
        Updated Credential, or None if not found
    """
    credential = db.get(Credential, credential_id)
    if credential is None:
        return None
    credential.value_encrypted = encrypt_value(value)
    db.commit()
    db.refresh(credential)
    return credential


def delete_credential(db: DBSession, credential_id: int) -> bool:
    """Delete a credential.

    Args:
        db: Database session
        credential_id: ID of credential to delete

    Returns:
        True if deleted, False if not found
    """
    credential = db.get(Credential, credential_id)
    if credential is None:
        return False
    db.delete(credential)
    db.commit()
    return True


def list_credentials(
    db: DBSession,
    provider: str | None = None,
) -> list[Credential]:
    """List credentials (without decrypting values).

    Args:
        db: Database session
        provider: Optional provider filter

    Returns:
        List of Credential models
    """
    stmt = select(Credential)
    if provider:
        stmt = stmt.where(Credential.provider == provider)
    stmt = stmt.order_by(Credential.provider, Credential.credential_type)
    return list(db.execute(stmt).scalars().all())


# Async versions for FastAPI endpoints


async def store_credential_async(
    db: AsyncSession,
    provider: str,
    credential_type: str,
    value: str,
) -> Credential:
    """Store an encrypted credential (async).

    Args:
        db: Async database session
        provider: Provider name (claude, gemini)
        credential_type: Type of credential (api_key, oauth_token, etc.)
        value: Plaintext credential value

    Returns:
        Created Credential model
    """
    encrypted = encrypt_value(value)
    credential = Credential(
        provider=provider,
        credential_type=credential_type,
        value_encrypted=encrypted,
    )
    db.add(credential)
    await db.commit()
    await db.refresh(credential)
    return credential


async def get_credential_async(
    db: AsyncSession,
    provider: str,
    credential_type: str,
) -> str | None:
    """Get a decrypted credential value (async).

    Args:
        db: Async database session
        provider: Provider name
        credential_type: Type of credential

    Returns:
        Decrypted credential value, or None if not found
    """
    stmt = select(Credential).where(
        Credential.provider == provider,
        Credential.credential_type == credential_type,
    )
    result = await db.execute(stmt)
    credential = result.scalar_one_or_none()
    if credential is None:
        return None
    return decrypt_value(credential.value_encrypted)


async def get_credential_by_id_async(
    db: AsyncSession,
    credential_id: int,
) -> Credential | None:
    """Get credential by ID (without decrypting) (async)."""
    return await db.get(Credential, credential_id)


async def update_credential_async(
    db: AsyncSession,
    credential_id: int,
    value: str,
) -> Credential | None:
    """Update an existing credential (async).

    Args:
        db: Async database session
        credential_id: ID of credential to update
        value: New plaintext value

    Returns:
        Updated Credential, or None if not found
    """
    credential = await db.get(Credential, credential_id)
    if credential is None:
        return None
    credential.value_encrypted = encrypt_value(value)
    await db.commit()
    await db.refresh(credential)
    return credential


async def delete_credential_async(db: AsyncSession, credential_id: int) -> bool:
    """Delete a credential (async).

    Args:
        db: Async database session
        credential_id: ID of credential to delete

    Returns:
        True if deleted, False if not found
    """
    credential = await db.get(Credential, credential_id)
    if credential is None:
        return False
    await db.delete(credential)
    await db.commit()
    return True


async def list_credentials_async(
    db: AsyncSession,
    provider: str | None = None,
) -> list[Credential]:
    """List credentials (without decrypting values) (async).

    Args:
        db: Async database session
        provider: Optional provider filter

    Returns:
        List of Credential models
    """
    stmt = select(Credential)
    if provider:
        stmt = stmt.where(Credential.provider == provider)
    stmt = stmt.order_by(Credential.provider, Credential.credential_type)
    result = await db.execute(stmt)
    return list(result.scalars().all())
