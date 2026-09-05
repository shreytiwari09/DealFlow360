"""Password hashing.

SECURITY_SPEC.md Section 3: Argon2id, never plaintext, never logged. JWT
issuing and verification join this module when login is built.

Argon2 was adopted at the Phase 3 Section 0.5 checkpoint. Its work-factor
parameters are encoded inside the hash string itself, which is why
`needs_rehash` below can exist: raising the cost later does not invalidate
existing hashes, they are simply upgraded the next time each user logs in.
"""

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

# Library defaults are the Argon2id RFC 9106 low-memory profile and are
# deliberately not tuned down. Hashing takes roughly 50-100ms, which is the
# point: it is what makes offline brute force expensive.
_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    """Return an Argon2id digest. The plaintext is never stored or logged."""
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """Check a candidate password against a stored digest.

    Returns False rather than raising for every failure mode, including a
    malformed or truncated stored hash. A corrupted row must read as "wrong
    password", not as a 500 that tells an attacker the account exists -
    SECURITY_SPEC.md Section 3 requires generic auth failures.
    """
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    """True when a stored hash used weaker parameters than the current policy.

    Call on successful login and, if True, re-hash the password the user has
    just proved they know. That is the only moment the plaintext is available.
    """
    try:
        return _hasher.check_needs_rehash(password_hash)
    except InvalidHashError:
        return True
