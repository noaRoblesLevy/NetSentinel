"""Alert management endpoints."""

import logging
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database import get_db

logger = logging.getLogger(__name__)
router = APIRouter()


class AlertResponse(BaseModel):
    """Alert response model."""
    id: str
    site_id: str
    asset_id: str
    alert_type: str
    severity: str
    status: str
    title: str
    description: Optional[str] = None
    peak_score: Optional[float] = None
    start_time: datetime
    end_time: Optional[datetime] = None
    explanation: Optional[dict] = None
    created_at: datetime


class AlertListResponse(BaseModel):
    """Paginated alert list response."""
    items: List[AlertResponse]
    total: int
    page: int
    page_size: int
    pages: int
    summary: dict


class AlertUpdate(BaseModel):
    """Alert update request."""
    status: Optional[str] = None
    resolution_notes: Optional[str] = None


@router.get("", response_model=AlertListResponse)
async def list_alerts(
    site_id: str,
    status_filter: Optional[str] = Query(None, alias="status"),
    severity: Optional[str] = None,
    asset_id: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db)
):
    """List alerts with filtering and pagination."""
    try:
        # Build query
        where_clauses = ["site_id = :site_id"]
        params = {"site_id": site_id}

        if status_filter:
            where_clauses.append("status = :status")
            params["status"] = status_filter

        if severity:
            where_clauses.append("severity = :severity")
            params["severity"] = severity

        if asset_id:
            where_clauses.append("asset_id = :asset_id")
            params["asset_id"] = asset_id

        where_sql = " AND ".join(where_clauses)

        # Get total count
        count_result = db.execute(
            text(f"SELECT COUNT(*) FROM alerts WHERE {where_sql}"),
            params
        )
        total = count_result.scalar()

        # Get summary
        summary_result = db.execute(
            text("""
                SELECT
                    COUNT(*) FILTER (WHERE status = 'open') as open,
                    COUNT(*) FILTER (WHERE status = 'acknowledged') as acknowledged,
                    COUNT(*) FILTER (WHERE status = 'investigating') as investigating,
                    COUNT(*) FILTER (WHERE status = 'resolved') as resolved,
                    COUNT(*) FILTER (WHERE severity = 'critical') as critical,
                    COUNT(*) FILTER (WHERE severity = 'high') as high,
                    COUNT(*) FILTER (WHERE severity = 'medium') as medium,
                    COUNT(*) FILTER (WHERE severity = 'low') as low
                FROM alerts
                WHERE site_id = :site_id
            """),
            {"site_id": site_id}
        )
        summary_row = summary_result.fetchone()

        # Get paginated results
        offset = (page - 1) * page_size
        result = db.execute(
            text(f"""
                SELECT id, site_id, asset_id, alert_type, severity, status,
                       title, description, peak_score, start_time, end_time, created_at
                FROM alerts
                WHERE {where_sql}
                ORDER BY created_at DESC
                LIMIT :limit OFFSET :offset
            """),
            {**params, "limit": page_size, "offset": offset}
        )

        items = []
        for row in result:
            items.append(AlertResponse(
                id=str(row.id),
                site_id=str(row.site_id),
                asset_id=str(row.asset_id),
                alert_type=row.alert_type,
                severity=row.severity,
                status=row.status,
                title=row.title,
                description=row.description,
                peak_score=row.peak_score,
                start_time=row.start_time,
                end_time=row.end_time,
                created_at=row.created_at
            ))

        return AlertListResponse(
            items=items,
            total=total,
            page=page,
            page_size=page_size,
            pages=(total + page_size - 1) // page_size if total > 0 else 1,
            summary={
                "open": summary_row.open or 0,
                "acknowledged": summary_row.acknowledged or 0,
                "investigating": summary_row.investigating or 0,
                "resolved": summary_row.resolved or 0,
                "by_severity": {
                    "critical": summary_row.critical or 0,
                    "high": summary_row.high or 0,
                    "medium": summary_row.medium or 0,
                    "low": summary_row.low or 0
                }
            }
        )

    except Exception as e:
        logger.error(f"Failed to list alerts: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.get("/by-severity")
def get_alerts_by_severity(
    site_id: str,
    db: Session = Depends(get_db)
):
    """Get alert counts by severity for pie chart."""
    try:
        result = db.execute(
            text("""
                SELECT
                    COUNT(*) FILTER (WHERE severity = 'critical' AND status = 'open') as critical,
                    COUNT(*) FILTER (WHERE severity = 'high' AND status = 'open') as high,
                    COUNT(*) FILTER (WHERE severity = 'medium' AND status = 'open') as medium,
                    COUNT(*) FILTER (WHERE severity = 'low' AND status = 'open') as low
                FROM alerts
                WHERE site_id = :site_id
            """),
            {"site_id": site_id}
        )
        row = result.fetchone()
        return {
            "critical": row.critical or 0,
            "high": row.high or 0,
            "medium": row.medium or 0,
            "low": row.low or 0
        }
    except Exception as e:
        logger.error(f"Failed to get alerts by severity: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{alert_id}", response_model=AlertResponse)
def get_alert(
    alert_id: str,
    db: Session = Depends(get_db)
):
    """Get detailed alert information."""
    try:
        result = db.execute(
            text("""
                SELECT id, site_id, asset_id, alert_type, severity, status,
                       title, description, peak_score, start_time, end_time,
                       explanation, created_at
                FROM alerts
                WHERE id = :alert_id
            """),
            {"alert_id": alert_id}
        )
        row = result.fetchone()

        if not row:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Alert not found"
            )

        return AlertResponse(
            id=str(row.id),
            site_id=str(row.site_id),
            asset_id=str(row.asset_id),
            alert_type=row.alert_type,
            severity=row.severity,
            status=row.status,
            title=row.title,
            description=row.description,
            peak_score=row.peak_score,
            start_time=row.start_time,
            end_time=row.end_time,
            explanation=row.explanation,
            created_at=row.created_at
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get alert: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.patch("/{alert_id}", response_model=AlertResponse)
async def update_alert(
    alert_id: str,
    update: AlertUpdate,
    db: Session = Depends(get_db)
):
    """Update alert status."""
    try:
        updates = []
        params = {"alert_id": alert_id}

        if update.status is not None:
            updates.append("status = :status")
            updates.append("status_changed_at = NOW()")
            params["status"] = update.status

        if update.resolution_notes is not None:
            updates.append("resolution_notes = :resolution_notes")
            params["resolution_notes"] = update.resolution_notes

        if updates:
            updates.append("updated_at = NOW()")
            db.execute(
                text(f"UPDATE alerts SET {', '.join(updates)} WHERE id = :alert_id"),
                params
            )
            db.commit()

        return await get_alert(alert_id, db)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update alert: {e}")
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )
