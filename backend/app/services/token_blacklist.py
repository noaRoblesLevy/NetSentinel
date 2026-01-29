"""
Token blacklist service using Redis for JWT invalidation.

This service allows tokens to be invalidated on logout, preventing
their use even before they expire.
"""

import logging
from typing import Optional
from datetime import datetime, timedelta

import redis
from jose import jwt, JWTError

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

# Redis key prefix for blacklisted tokens
BLACKLIST_PREFIX = "token_blacklist:"

# Redis connection pool (lazy initialized)
_redis_client: Optional[redis.Redis] = None


def get_redis_client() -> redis.Redis:
    """Get or create Redis client connection."""
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.from_url(
            settings.redis_url,
            decode_responses=True,
            socket_connect_timeout=5,
            socket_timeout=5,
        )
    return _redis_client


def _get_token_jti(token: str) -> Optional[str]:
    """
    Extract the JTI (JWT ID) or create a unique identifier from token.

    If the token doesn't have a JTI claim, we use a hash of the token.
    """
    try:
        # Decode without verification to get claims
        payload = jwt.decode(
            token,
            settings.secret_key,
            algorithms=[settings.algorithm],
            options={"verify_exp": False}  # Allow expired tokens for blacklisting
        )

        # Use JTI if present, otherwise hash the token
        jti = payload.get("jti")
        if not jti:
            # Create a unique identifier from token signature
            import hashlib
            jti = hashlib.sha256(token.encode()).hexdigest()[:32]

        return jti
    except JWTError as e:
        logger.warning(f"Failed to decode token for blacklisting: {e}")
        return None


def _get_token_expiry(token: str) -> Optional[int]:
    """Get the remaining TTL for a token in seconds."""
    try:
        payload = jwt.decode(
            token,
            settings.secret_key,
            algorithms=[settings.algorithm],
            options={"verify_exp": False}
        )
        exp = payload.get("exp")
        if exp:
            expiry_time = datetime.utcfromtimestamp(exp)
            remaining = (expiry_time - datetime.utcnow()).total_seconds()
            return max(int(remaining), 0)
        return None
    except JWTError:
        return None


def blacklist_token(token: str) -> bool:
    """
    Add a token to the blacklist.

    The token is stored in Redis with a TTL equal to its remaining lifetime.
    This ensures the blacklist entry is automatically cleaned up when the
    token would have expired anyway.

    Returns True if successful, False otherwise.
    """
    try:
        jti = _get_token_jti(token)
        if not jti:
            return False

        ttl = _get_token_expiry(token)
        if ttl is None or ttl <= 0:
            # Token already expired, no need to blacklist
            return True

        client = get_redis_client()
        key = f"{BLACKLIST_PREFIX}{jti}"

        # Store with TTL (value is timestamp of blacklisting)
        client.setex(key, ttl, datetime.utcnow().isoformat())

        logger.debug(f"Token blacklisted: {jti[:8]}... (TTL: {ttl}s)")
        return True

    except redis.RedisError as e:
        logger.error(f"Redis error while blacklisting token: {e}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error while blacklisting token: {e}")
        return False


def is_token_blacklisted(token: str) -> bool:
    """
    Check if a token is blacklisted.

    Returns True if the token is blacklisted or if Redis is unavailable.
    Fails closed for security - if we can't verify, we reject.
    """
    try:
        jti = _get_token_jti(token)
        if not jti:
            return False

        client = get_redis_client()
        key = f"{BLACKLIST_PREFIX}{jti}"

        return client.exists(key) > 0

    except redis.RedisError as e:
        logger.error(f"Redis error while checking blacklist: {e}")
        # Fail-closed: if Redis is down, treat all tokens as potentially revoked
        # Security takes priority over availability for token validation
        return True
    except Exception as e:
        logger.error(f"Unexpected error while checking blacklist: {e}")
        return True


def blacklist_user_tokens(user_email: str, issued_before: Optional[datetime] = None) -> bool:
    """
    Blacklist all tokens for a specific user.

    This is useful for:
    - Password changes (invalidate all existing sessions)
    - Account deactivation
    - Security incidents

    Note: This is implemented by storing the user's invalidation timestamp.
    Tokens issued before this timestamp are considered invalid.
    """
    try:
        client = get_redis_client()
        key = f"{BLACKLIST_PREFIX}user:{user_email}"

        timestamp = (issued_before or datetime.utcnow()).isoformat()

        # Store for 7 days (max refresh token lifetime)
        ttl = int(timedelta(days=7).total_seconds())
        client.setex(key, ttl, timestamp)

        logger.info(f"All tokens blacklisted for user: {user_email}")
        return True

    except redis.RedisError as e:
        logger.error(f"Redis error while blacklisting user tokens: {e}")
        return False


def is_user_token_invalidated(user_email: str, token_issued_at: datetime) -> bool:
    """
    Check if a user's tokens issued before a certain time are invalidated.
    Fails closed for security - if Redis is unavailable, treat tokens as invalid.
    """
    try:
        client = get_redis_client()
        key = f"{BLACKLIST_PREFIX}user:{user_email}"

        invalidation_time = client.get(key)
        if invalidation_time:
            invalidation_dt = datetime.fromisoformat(invalidation_time)
            return token_issued_at < invalidation_dt

        return False

    except redis.RedisError as e:
        logger.error(f"Redis error while checking user invalidation: {e}")
        # Fail-closed: if Redis is down, require re-authentication
        return True
    except Exception as e:
        logger.error(f"Unexpected error while checking user invalidation: {e}")
        return True
