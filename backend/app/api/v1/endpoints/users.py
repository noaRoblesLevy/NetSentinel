"""User management endpoints (admin only)."""

import logging
from typing import Optional, List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User
from app.api.v1.endpoints.auth import get_current_user, require_admin, hash_password, validate_password_complexity

logger = logging.getLogger(__name__)
router = APIRouter()


class UserCreate(BaseModel):
    """Request model for creating a user."""
    email: EmailStr
    password: str
    full_name: str
    role: str = "viewer"


class UserUpdate(BaseModel):
    """Request model for updating a user."""
    email: Optional[EmailStr] = None
    full_name: Optional[str] = None
    role: Optional[str] = None
    is_active: Optional[bool] = None


class UserResponse(BaseModel):
    """User response model."""
    id: str
    email: str
    full_name: str
    role: str
    is_active: bool
    created_at: str
    last_login_at: Optional[str] = None

    class Config:
        from_attributes = True


@router.get("", response_model=List[UserResponse])
def list_users(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """List all users (admin only)."""
    users = db.query(User).order_by(User.created_at.desc()).all()
    return [
        UserResponse(
            id=str(u.id),
            email=u.email,
            full_name=u.full_name,
            role=u.role,
            is_active=u.is_active,
            created_at=u.created_at.isoformat() if u.created_at else "",
            last_login_at=u.last_login_at.isoformat() if u.last_login_at else None
        )
        for u in users
    ]


@router.get("/{user_id}", response_model=UserResponse)
def get_user(
    user_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """Get a specific user by ID (admin only)."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    return UserResponse(
        id=str(user.id),
        email=user.email,
        full_name=user.full_name,
        role=user.role,
        is_active=user.is_active,
        created_at=user.created_at.isoformat() if user.created_at else "",
        last_login_at=user.last_login_at.isoformat() if user.last_login_at else None
    )


@router.post("", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def create_user(
    user_data: UserCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """Create a new user (admin only)."""
    # Check if email already exists
    existing = db.query(User).filter(User.email == user_data.email).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email address is already registered"
        )

    # Validate role
    valid_roles = ["admin", "analyst", "viewer"]
    if user_data.role not in valid_roles:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid role. Must be one of: {', '.join(valid_roles)}"
        )

    # Validate password complexity
    is_valid, error_msg = validate_password_complexity(user_data.password)
    if not is_valid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=error_msg
        )

    # Create user
    hashed_pw = hash_password(user_data.password)
    result = db.execute(
        text("""
            INSERT INTO users (email, hashed_password, full_name, role, is_active, created_at)
            VALUES (:email, :password, :full_name, :role, true, NOW())
            RETURNING id, created_at
        """),
        {
            "email": user_data.email,
            "password": hashed_pw,
            "full_name": user_data.full_name,
            "role": user_data.role
        }
    )
    row = result.fetchone()
    db.commit()

    logger.info(f"User created: {user_data.email} by {current_user.email}")

    return UserResponse(
        id=str(row.id),
        email=user_data.email,
        full_name=user_data.full_name,
        role=user_data.role,
        is_active=True,
        created_at=row.created_at.isoformat()
    )


@router.patch("/{user_id}", response_model=UserResponse)
def update_user(
    user_id: UUID,
    user_data: UserUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """Update a user (admin only)."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    # Prevent admin from deactivating themselves
    if user.id == current_user.id and user_data.is_active is False:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot deactivate your own account"
        )

    # Prevent admin from removing their own admin role
    if user.id == current_user.id and user_data.role and user_data.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot remove your own admin role"
        )

    updates = []
    params = {"user_id": str(user_id)}

    if user_data.email is not None:
        # Check if email is taken by another user
        existing = db.query(User).filter(User.email == user_data.email, User.id != user_id).first()
        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email address is already in use"
            )
        updates.append("email = :email")
        params["email"] = user_data.email

    if user_data.full_name is not None:
        updates.append("full_name = :full_name")
        params["full_name"] = user_data.full_name

    if user_data.role is not None:
        valid_roles = ["admin", "analyst", "viewer"]
        if user_data.role not in valid_roles:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid role. Must be one of: {', '.join(valid_roles)}"
            )
        updates.append("role = :role")
        params["role"] = user_data.role

    if user_data.is_active is not None:
        updates.append("is_active = :is_active")
        params["is_active"] = user_data.is_active

    if updates:
        updates.append("updated_at = NOW()")
        query = f"UPDATE users SET {', '.join(updates)} WHERE id = :user_id"
        db.execute(text(query), params)
        db.commit()
        db.refresh(user)

    logger.info(f"User updated: {user.email} by {current_user.email}")

    return UserResponse(
        id=str(user.id),
        email=user.email,
        full_name=user.full_name,
        role=user.role,
        is_active=user.is_active,
        created_at=user.created_at.isoformat() if user.created_at else "",
        last_login_at=user.last_login_at.isoformat() if user.last_login_at else None
    )


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(
    user_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """Delete a user (admin only)."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    # Prevent admin from deleting themselves
    if user.id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete your own account"
        )

    db.delete(user)
    db.commit()

    logger.info(f"User deleted: {user.email} by {current_user.email}")
    return None


class PasswordReset(BaseModel):
    """Request model for admin password reset."""
    new_password: str


@router.post("/{user_id}/reset-password", status_code=status.HTTP_200_OK)
def admin_reset_password(
    user_id: UUID,
    data: PasswordReset,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """Reset a user's password (admin only)."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    # Validate password complexity
    is_valid, error_msg = validate_password_complexity(data.new_password)
    if not is_valid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=error_msg
        )

    # Hash and save new password
    new_hash = hash_password(data.new_password)
    db.execute(
        text("UPDATE users SET hashed_password = :password, updated_at = NOW() WHERE id = :user_id"),
        {"password": new_hash, "user_id": str(user_id)}
    )
    db.commit()

    # Invalidate all existing tokens for this user
    from app.services.token_blacklist import blacklist_user_tokens
    blacklist_user_tokens(user.email)

    logger.info(f"Password reset by admin for user: {user.email} by {current_user.email}")

    return {"message": f"Password reset successfully for {user.email}"}
