"""Authentication endpoints with JWT access and refresh tokens."""

import logging
from datetime import datetime, timedelta
from typing import Optional

import bcrypt
from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import JWTError, jwt
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.database import get_db
from app.config import get_settings
from app.models import User
from app.services.token_blacklist import (
    blacklist_token,
    is_token_blacklisted,
    is_user_token_invalidated,
)

logger = logging.getLogger(__name__)
router = APIRouter()

settings = get_settings()

# JWT settings
SECRET_KEY = settings.secret_key
ALGORITHM = settings.algorithm
ACCESS_TOKEN_EXPIRE_MINUTES = settings.access_token_expire_minutes
REFRESH_TOKEN_EXPIRE_DAYS = 7

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")


class Token(BaseModel):
    """Token response model."""
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int = Field(description="Access token expiry in seconds")


class TokenData(BaseModel):
    """Decoded token data."""
    email: Optional[str] = None
    token_type: str = "access"


class RefreshTokenRequest(BaseModel):
    """Request model for token refresh."""
    refresh_token: str


class UserResponse(BaseModel):
    """User information response model."""
    id: str
    email: str
    full_name: str
    role: str
    is_active: bool

    class Config:
        from_attributes = True


class AuthResponse(BaseModel):
    """Authentication response with tokens and user info."""
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserResponse


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against its hash."""
    try:
        return bcrypt.checkpw(
            plain_password.encode('utf-8'),
            hashed_password.encode('utf-8')
        )
    except Exception:
        return False


def hash_password(password: str) -> str:
    """Hash a password using bcrypt."""
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """Create a JWT access token."""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({
        "exp": expire,
        "type": "access",
        "iat": datetime.utcnow()
    })
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def create_refresh_token(data: dict) -> str:
    """Create a JWT refresh token with longer expiry."""
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    to_encode.update({
        "exp": expire,
        "type": "refresh",
        "iat": datetime.utcnow()
    })
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str, expected_type: str = "access") -> dict:
    """Decode and validate a JWT token."""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        token_type = payload.get("type", "access")
        if token_type != expected_type:
            raise JWTError(f"Expected {expected_type} token, got {token_type}")
        return payload
    except JWTError as e:
        logger.warning(f"Token decode failed: {e}")
        raise


def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db)
) -> User:
    """Get the current authenticated user from JWT token."""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    # Check if token is blacklisted
    if is_token_blacklisted(token):
        logger.warning("Attempted use of blacklisted token")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has been revoked",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        payload = decode_token(token, expected_type="access")
        email: str = payload.get("sub")
        if email is None:
            raise credentials_exception

        # Check if user's tokens were invalidated (e.g., password change)
        iat = payload.get("iat")
        if iat:
            token_issued_at = datetime.utcfromtimestamp(iat)
            if is_user_token_invalidated(email, token_issued_at):
                logger.warning(f"Token invalidated for user: {email}")
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Session expired, please login again",
                    headers={"WWW-Authenticate": "Bearer"},
                )

    except JWTError:
        raise credentials_exception

    user = db.query(User).filter(User.email == email).first()

    if user is None:
        raise credentials_exception
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is disabled"
        )
    return user


def require_role(allowed_roles: list[str]):
    """Dependency to check user role."""
    def role_checker(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role '{current_user.role}' is not authorized for this action"
            )
        return current_user
    return role_checker


# Role-based dependencies for convenience
require_admin = require_role(["admin"])
require_analyst = require_role(["admin", "analyst"])
require_viewer = require_role(["admin", "analyst", "viewer"])


@router.post("/login", response_model=AuthResponse)
def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db)
):
    """
    Authenticate user and return access + refresh tokens.

    The access token expires in 60 minutes and should be used for API calls.
    The refresh token expires in 7 days and can be used to get new tokens.
    """
    # Find user by email
    user = db.query(User).filter(User.email == form_data.username).first()

    if not user:
        logger.warning(f"Login attempt for non-existent user: {form_data.username}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Verify password
    if not verify_password(form_data.password, user.hashed_password):
        logger.warning(f"Failed login attempt for user: {form_data.username}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is disabled"
        )

    # Create tokens
    token_data = {"sub": user.email, "role": user.role}
    access_token = create_access_token(data=token_data)
    refresh_token = create_refresh_token(data=token_data)

    # Update last login
    try:
        db.execute(
            text("UPDATE users SET last_login_at = NOW() WHERE id = :user_id"),
            {"user_id": str(user.id)}
        )
        db.commit()
    except Exception as e:
        logger.error(f"Failed to update last_login_at: {e}")

    logger.info(f"User logged in: {user.email}")

    return AuthResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
        expires_in=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        user=UserResponse(
            id=str(user.id),
            email=user.email,
            full_name=user.full_name,
            role=user.role,
            is_active=user.is_active
        )
    )


@router.post("/refresh", response_model=Token)
def refresh_token(
    request: RefreshTokenRequest,
    db: Session = Depends(get_db)
):
    """
    Get new access and refresh tokens using a valid refresh token.

    Use this when the access token has expired but you still have a valid refresh token.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired refresh token",
        headers={"WWW-Authenticate": "Bearer"},
    )

    # Check if refresh token is blacklisted
    if is_token_blacklisted(request.refresh_token):
        logger.warning("Attempted use of blacklisted refresh token")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token has been revoked",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        payload = decode_token(request.refresh_token, expected_type="refresh")
        email: str = payload.get("sub")
        if email is None:
            raise credentials_exception

        # Check if user's tokens were invalidated
        iat = payload.get("iat")
        if iat:
            token_issued_at = datetime.utcfromtimestamp(iat)
            if is_user_token_invalidated(email, token_issued_at):
                logger.warning(f"Refresh token invalidated for user: {email}")
                raise credentials_exception

    except JWTError:
        raise credentials_exception

    # Verify user still exists and is active
    user = db.query(User).filter(User.email == email).first()
    if user is None or not user.is_active:
        raise credentials_exception

    # Blacklist the old refresh token (rotation)
    blacklist_token(request.refresh_token)

    # Create new tokens
    token_data = {"sub": user.email, "role": user.role}
    new_access_token = create_access_token(data=token_data)
    new_refresh_token = create_refresh_token(data=token_data)

    logger.info(f"Tokens refreshed for user: {user.email}")

    return Token(
        access_token=new_access_token,
        refresh_token=new_refresh_token,
        token_type="bearer",
        expires_in=ACCESS_TOKEN_EXPIRE_MINUTES * 60
    )


@router.get("/me", response_model=UserResponse)
def get_me(current_user: User = Depends(get_current_user)):
    """Get current authenticated user info."""
    return UserResponse(
        id=str(current_user.id),
        email=current_user.email,
        full_name=current_user.full_name,
        role=current_user.role,
        is_active=current_user.is_active
    )


class LogoutRequest(BaseModel):
    """Request model for logout with optional refresh token."""
    refresh_token: Optional[str] = None


@router.post("/logout")
def logout(
    request: Optional[LogoutRequest] = None,
    token: str = Depends(oauth2_scheme),
    current_user: User = Depends(get_current_user)
):
    """
    Logout endpoint - invalidates the current access token and optionally the refresh token.

    The access token is automatically blacklisted. If a refresh token is provided,
    it will also be blacklisted to prevent it from being used to get new tokens.
    """
    # Blacklist the access token
    if not blacklist_token(token):
        logger.warning(f"Failed to blacklist access token for user: {current_user.email}")

    # Blacklist the refresh token if provided
    if request and request.refresh_token:
        if not blacklist_token(request.refresh_token):
            logger.warning(f"Failed to blacklist refresh token for user: {current_user.email}")

    logger.info(f"User logged out: {current_user.email}")
    return {"message": "Successfully logged out", "email": current_user.email}
