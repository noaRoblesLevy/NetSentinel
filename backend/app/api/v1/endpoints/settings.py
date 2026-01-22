"""User and site settings endpoints."""

import logging
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User
from app.api.v1.endpoints.auth import get_current_user, require_viewer, require_admin

logger = logging.getLogger(__name__)
router = APIRouter()


class NotificationSettings(BaseModel):
    """Notification settings for a site."""
    email_enabled: bool = False
    email_address: Optional[str] = None
    webhook_enabled: bool = False
    webhook_url: Optional[str] = None
    slack_enabled: bool = False
    slack_webhook_url: Optional[str] = None
    min_severity: str = "medium"


class NotificationSettingsResponse(BaseModel):
    """Response for notification settings."""
    site_id: str
    settings: NotificationSettings


def ensure_settings_table(db: Session):
    """Ensure the notification_settings table exists."""
    db.execute(text("""
        CREATE TABLE IF NOT EXISTS notification_settings (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            site_id UUID NOT NULL REFERENCES sites(id) ON DELETE CASCADE,
            user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            email_enabled BOOLEAN NOT NULL DEFAULT false,
            email_address VARCHAR(255),
            webhook_enabled BOOLEAN NOT NULL DEFAULT false,
            webhook_url TEXT,
            slack_enabled BOOLEAN NOT NULL DEFAULT false,
            slack_webhook_url TEXT,
            min_severity VARCHAR(20) NOT NULL DEFAULT 'medium',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ,
            UNIQUE(site_id, user_id)
        )
    """))
    db.commit()


@router.get("/notifications/{site_id}", response_model=NotificationSettingsResponse)
def get_notification_settings(
    site_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_viewer)
):
    """Get notification settings for a site."""
    ensure_settings_table(db)

    result = db.execute(
        text("""
            SELECT email_enabled, email_address, webhook_enabled, webhook_url,
                   slack_enabled, slack_webhook_url, min_severity
            FROM notification_settings
            WHERE site_id = :site_id AND user_id = :user_id
        """),
        {"site_id": str(site_id), "user_id": str(current_user.id)}
    )
    row = result.fetchone()

    if row:
        settings = NotificationSettings(
            email_enabled=row.email_enabled,
            email_address=row.email_address,
            webhook_enabled=row.webhook_enabled,
            webhook_url=row.webhook_url,
            slack_enabled=row.slack_enabled,
            slack_webhook_url=row.slack_webhook_url,
            min_severity=row.min_severity
        )
    else:
        # Return defaults
        settings = NotificationSettings()

    return NotificationSettingsResponse(
        site_id=str(site_id),
        settings=settings
    )


@router.put("/notifications/{site_id}", response_model=NotificationSettingsResponse)
def update_notification_settings(
    site_id: UUID,
    settings: NotificationSettings,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_viewer)
):
    """Update notification settings for a site."""
    ensure_settings_table(db)

    # Upsert settings
    db.execute(
        text("""
            INSERT INTO notification_settings (
                site_id, user_id, email_enabled, email_address,
                webhook_enabled, webhook_url, slack_enabled, slack_webhook_url,
                min_severity
            ) VALUES (
                :site_id, :user_id, :email_enabled, :email_address,
                :webhook_enabled, :webhook_url, :slack_enabled, :slack_webhook_url,
                :min_severity
            )
            ON CONFLICT (site_id, user_id) DO UPDATE SET
                email_enabled = EXCLUDED.email_enabled,
                email_address = EXCLUDED.email_address,
                webhook_enabled = EXCLUDED.webhook_enabled,
                webhook_url = EXCLUDED.webhook_url,
                slack_enabled = EXCLUDED.slack_enabled,
                slack_webhook_url = EXCLUDED.slack_webhook_url,
                min_severity = EXCLUDED.min_severity,
                updated_at = NOW()
        """),
        {
            "site_id": str(site_id),
            "user_id": str(current_user.id),
            "email_enabled": settings.email_enabled,
            "email_address": settings.email_address,
            "webhook_enabled": settings.webhook_enabled,
            "webhook_url": settings.webhook_url,
            "slack_enabled": settings.slack_enabled,
            "slack_webhook_url": settings.slack_webhook_url,
            "min_severity": settings.min_severity
        }
    )
    db.commit()

    logger.info(f"Notification settings updated for site {site_id} by user {current_user.email}")

    return NotificationSettingsResponse(
        site_id=str(site_id),
        settings=settings
    )
