"""Asset management endpoints."""

import logging
from datetime import datetime
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User
from app.api.v1.endpoints.auth import get_current_user, require_viewer, require_analyst

logger = logging.getLogger(__name__)
router = APIRouter()


class AssetResponse(BaseModel):
    """Asset response model."""
    id: str
    site_id: str
    ip: str
    hostname: Optional[str] = None
    role_tag: str = "unknown"
    custom_name: Optional[str] = None
    subnet_label: Optional[str] = None
    first_seen: datetime
    last_seen: datetime
    is_monitored: bool = True


class AssetListResponse(BaseModel):
    """Paginated asset list response."""
    items: List[AssetResponse]
    total: int
    page: int
    page_size: int


class AssetUpdate(BaseModel):
    """Asset update request."""
    custom_name: Optional[str] = None
    role_tag: Optional[str] = None
    is_monitored: Optional[bool] = None
    notes: Optional[str] = None


@router.get("", response_model=AssetListResponse)
async def list_assets(
    site_id: str,
    role_tag: Optional[str] = None,
    search: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_viewer)
):
    """List discovered assets for a site."""
    try:
        # Build query
        where_clauses = ["site_id = :site_id"]
        params = {"site_id": site_id}

        if role_tag:
            where_clauses.append("role_tag = :role_tag")
            params["role_tag"] = role_tag

        if search:
            where_clauses.append("(ip::text LIKE :search OR hostname LIKE :search OR custom_name LIKE :search)")
            params["search"] = f"%{search}%"

        where_sql = " AND ".join(where_clauses)

        # Get total count
        count_result = db.execute(
            text(f"SELECT COUNT(*) FROM assets WHERE {where_sql}"),
            params
        )
        total = count_result.scalar()

        # Get paginated results
        offset = (page - 1) * page_size
        result = db.execute(
            text(f"""
                SELECT id, site_id, ip, hostname, role_tag, custom_name,
                       subnet_label, first_seen, last_seen, is_monitored
                FROM assets
                WHERE {where_sql}
                ORDER BY last_seen DESC
                LIMIT :limit OFFSET :offset
            """),
            {**params, "limit": page_size, "offset": offset}
        )

        items = []
        for row in result:
            items.append(AssetResponse(
                id=str(row.id),
                site_id=str(row.site_id),
                ip=str(row.ip),
                hostname=row.hostname,
                role_tag=row.role_tag,
                custom_name=row.custom_name,
                subnet_label=row.subnet_label,
                first_seen=row.first_seen,
                last_seen=row.last_seen,
                is_monitored=row.is_monitored
            ))

        return AssetListResponse(
            items=items,
            total=total,
            page=page,
            page_size=page_size
        )

    except Exception as e:
        logger.error(f"Failed to list assets: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve assets"
        )


@router.get("/{asset_id}", response_model=AssetResponse)
async def get_asset(
    asset_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_viewer)
):
    """Get detailed asset information."""
    try:
        result = db.execute(
            text("""
                SELECT id, site_id, ip, hostname, role_tag, custom_name,
                       subnet_label, first_seen, last_seen, is_monitored
                FROM assets
                WHERE id = :asset_id
            """),
            {"asset_id": asset_id}
        )
        row = result.fetchone()

        if not row:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Asset not found"
            )

        return AssetResponse(
            id=str(row.id),
            site_id=str(row.site_id),
            ip=str(row.ip),
            hostname=row.hostname,
            role_tag=row.role_tag,
            custom_name=row.custom_name,
            subnet_label=row.subnet_label,
            first_seen=row.first_seen,
            last_seen=row.last_seen,
            is_monitored=row.is_monitored
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get asset: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve asset details"
        )


@router.patch("/{asset_id}", response_model=AssetResponse)
async def update_asset(
    asset_id: str,
    update: AssetUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_analyst)
):
    """Update asset details."""
    try:
        # Build update query
        updates = []
        params = {"asset_id": asset_id}

        if update.custom_name is not None:
            updates.append("custom_name = :custom_name")
            params["custom_name"] = update.custom_name

        if update.role_tag is not None:
            updates.append("role_tag = :role_tag")
            params["role_tag"] = update.role_tag

        if update.is_monitored is not None:
            updates.append("is_monitored = :is_monitored")
            params["is_monitored"] = update.is_monitored

        if update.notes is not None:
            updates.append("notes = :notes")
            params["notes"] = update.notes

        if updates:
            updates.append("updated_at = NOW()")
            db.execute(
                text(f"UPDATE assets SET {', '.join(updates)} WHERE id = :asset_id"),
                params
            )
            db.commit()

        # Return updated asset
        return await get_asset(asset_id, db)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update asset: {e}")
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update asset"
        )
