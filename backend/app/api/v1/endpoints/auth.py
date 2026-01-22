"""Authentication endpoints with JWT access and refresh tokens."""

import logging
from datetime import datetime, timedelta
from typing import Optional

import bcrypt
from fastapi import APIRouter, Depends, HTTPException, status, Request, Response, Cookie
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

# Cookie settings
COOKIE_NAME = "access_token"
REFRESH_COOKIE_NAME = "refresh_token"
COOKIE_SECURE = settings.environment == "production"  # Only send over HTTPS in production
COOKIE_SAMESITE = "lax"  # Protect against CSRF while allowing normal navigation

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False)


def get_token_from_cookie_or_header(
    request: Request,
    token_from_header: Optional[str] = Depends(oauth2_scheme),
    access_token: Optional[str] = Cookie(None, alias=COOKIE_NAME),
) -> str:
    """
    Extract JWT token from either Authorization header or httpOnly cookie.

    Priority:
    1. Authorization header (Bearer token) - for API clients
    2. httpOnly cookie - for browser-based clients

    This allows both traditional API clients and browser-based apps to authenticate.
    """
    # Try header first (API clients)
    if token_from_header:
        return token_from_header

    # Fall back to cookie (browser clients)
    if access_token:
        return access_token

    # No token found
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated",
        headers={"WWW-Authenticate": "Bearer"},
    )


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
    request: Request,
    token: str = Depends(get_token_from_cookie_or_header),
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
    response: Response,
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db)
):
    """
    Authenticate user and return access + refresh tokens.

    The access token expires in 60 minutes and should be used for API calls.
    The refresh token expires in 7 days and can be used to get new tokens.

    Tokens are also set as httpOnly cookies for browser-based clients.
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

    # Set httpOnly cookies for browser clients
    response.set_cookie(
        key=COOKIE_NAME,
        value=access_token,
        httponly=True,
        secure=COOKIE_SECURE,
        samesite=COOKIE_SAMESITE,
        max_age=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        path="/",
    )
    response.set_cookie(
        key=REFRESH_COOKIE_NAME,
        value=refresh_token,
        httponly=True,
        secure=COOKIE_SECURE,
        samesite=COOKIE_SAMESITE,
        max_age=REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60,
        path="/api/v1/auth",  # Only send refresh token to auth endpoints
    )

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
def refresh_tokens(
    response: Response,
    body: Optional[RefreshTokenRequest] = None,
    refresh_token_cookie: Optional[str] = Cookie(None, alias=REFRESH_COOKIE_NAME),
    db: Session = Depends(get_db)
):
    """
    Get new access and refresh tokens using a valid refresh token.

    The refresh token can be provided in the request body (for API clients)
    or via httpOnly cookie (for browser clients).

    Use this when the access token has expired but you still have a valid refresh token.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired refresh token",
        headers={"WWW-Authenticate": "Bearer"},
    )

    # Get refresh token from body or cookie
    refresh_token = (body.refresh_token if body else None) or refresh_token_cookie
    if not refresh_token:
        raise credentials_exception

    # Check if refresh token is blacklisted
    if is_token_blacklisted(refresh_token):
        logger.warning("Attempted use of blacklisted refresh token")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token has been revoked",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        payload = decode_token(refresh_token, expected_type="refresh")
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
    blacklist_token(refresh_token)

    # Create new tokens
    token_data = {"sub": user.email, "role": user.role}
    new_access_token = create_access_token(data=token_data)
    new_refresh_token = create_refresh_token(data=token_data)

    # Set new cookies for browser clients
    response.set_cookie(
        key=COOKIE_NAME,
        value=new_access_token,
        httponly=True,
        secure=COOKIE_SECURE,
        samesite=COOKIE_SAMESITE,
        max_age=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        path="/",
    )
    response.set_cookie(
        key=REFRESH_COOKIE_NAME,
        value=new_refresh_token,
        httponly=True,
        secure=COOKIE_SECURE,
        samesite=COOKIE_SAMESITE,
        max_age=REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60,
        path="/api/v1/auth",
    )

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
    response: Response,
    http_request: Request,
    body: Optional[LogoutRequest] = None,
    token: str = Depends(get_token_from_cookie_or_header),
    refresh_token_cookie: Optional[str] = Cookie(None, alias=REFRESH_COOKIE_NAME),
    current_user: User = Depends(get_current_user)
):
    """
    Logout endpoint - invalidates the current access token and refresh token.

    The access token is automatically blacklisted. The refresh token from either
    the request body or cookie will also be blacklisted.

    Also clears httpOnly cookies for browser clients.
    """
    # Blacklist the access token
    if not blacklist_token(token):
        logger.warning(f"Failed to blacklist access token for user: {current_user.email}")

    # Blacklist the refresh token from body or cookie
    refresh_token = (body.refresh_token if body else None) or refresh_token_cookie
    if refresh_token:
        if not blacklist_token(refresh_token):
            logger.warning(f"Failed to blacklist refresh token for user: {current_user.email}")

    # Clear cookies for browser clients
    response.delete_cookie(key=COOKIE_NAME, path="/")
    response.delete_cookie(key=REFRESH_COOKIE_NAME, path="/api/v1/auth")

    logger.info(f"User logged out: {current_user.email}")
    return {"message": "Successfully logged out", "email": current_user.email}


class ProfileUpdate(BaseModel):
    """Request model for profile update."""
    full_name: Optional[str] = None
    email: Optional[str] = None


@router.patch("/me", response_model=UserResponse)
def update_profile(
    update: ProfileUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Update the current user's profile information."""
    updates = []
    params = {"user_id": str(current_user.id)}

    if update.full_name is not None:
        updates.append("full_name = :full_name")
        params["full_name"] = update.full_name

    if update.email is not None:
        # Check if email is already taken
        existing = db.query(User).filter(User.email == update.email, User.id != current_user.id).first()
        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email address is already in use"
            )
        updates.append("email = :email")
        params["email"] = update.email

    if updates:
        updates.append("updated_at = NOW()")
        query = f"UPDATE users SET {', '.join(updates)} WHERE id = :user_id"
        db.execute(text(query), params)
        db.commit()

        # Refresh user data
        db.refresh(current_user)

    logger.info(f"Profile updated for user: {current_user.email}")

    return UserResponse(
        id=str(current_user.id),
        email=current_user.email,
        full_name=current_user.full_name,
        role=current_user.role,
        is_active=current_user.is_active
    )


class PasswordChange(BaseModel):
    """Request model for password change."""
    current_password: str
    new_password: str


@router.post("/change-password")
def change_password(
    request: PasswordChange,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Change the current user's password."""
    # Verify current password
    if not verify_password(request.current_password, current_user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect"
        )

    # Validate new password
    if len(request.new_password) < 8:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="New password must be at least 8 characters long"
        )

    # Hash and save new password
    new_hash = hash_password(request.new_password)
    db.execute(
        text("UPDATE users SET hashed_password = :password, updated_at = NOW() WHERE id = :user_id"),
        {"password": new_hash, "user_id": str(current_user.id)}
    )
    db.commit()

    # Invalidate all existing tokens for this user
    from app.services.token_blacklist import blacklist_user_tokens
    blacklist_user_tokens(current_user.email)

    logger.info(f"Password changed for user: {current_user.email}")

    return {"message": "Password changed successfully. Please log in again."}
