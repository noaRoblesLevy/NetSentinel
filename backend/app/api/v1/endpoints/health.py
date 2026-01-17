"""Health check and status endpoints for system monitoring."""

import logging
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database import get_db
from app.services.system_status import SystemStatusService, FlowStatus, LearningPhase

logger = logging.getLogger(__name__)
router = APIRouter()

VERSION = "1.0.0"


class LearningStatusResponse(BaseModel):
    """Learning mode status details."""
    is_learning: bool
    phase: str
    progress_days: int
    target_days: int
    progress_percent: float
    estimated_completion: Optional[str]
    data_quality: str
    current_assets: int
    min_assets_for_training: int
    can_transition: bool
    alerts_suppressed: bool
    message: str


class SiteStatusResponse(BaseModel):
    """Response model for comprehensive site status."""
    site_id: str
    site_name: str
    flow_status: str
    last_flow_received: Optional[str]
    flows_last_hour: int
    flows_last_5min: int
    flows_last_24h: int
    bytes_last_24h: int
    learning: LearningStatusResponse
    active_alerts: int
    last_anomaly_score: Optional[float]
    model_trained: bool
    model_last_trained: Optional[str]
    last_check: str
    error_message: Optional[str]
    warnings: List[str]


@router.get("/health")
async def health_check():
    """Basic health check endpoint for load balancers."""
    return {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "version": VERSION
    }


@router.get("/health/detailed")
async def detailed_health_check(db: Session = Depends(get_db)):
    """Detailed health check with component status."""
    status_service = SystemStatusService(db)
    health = status_service.get_system_health()
    health["version"] = VERSION

    # Check Redis
    try:
        redis_health = status_service.check_redis_health()
        health["components"]["redis"] = {
            "status": redis_health.status.value,
            "message": redis_health.message
        }
    except Exception as e:
        health["components"]["redis"] = {
            "status": "unknown",
            "message": str(e)
        }

    return health


@router.get("/health/ready")
async def readiness_check(db: Session = Depends(get_db)):
    """Readiness check - is the service ready to accept traffic?"""
    try:
        # Check database is accessible
        db.execute(text("SELECT 1"))

        # Check required tables exist
        result = db.execute(text("""
            SELECT COUNT(*) FROM information_schema.tables
            WHERE table_name IN ('sites', 'flows_raw', 'assets', 'alerts')
        """))
        table_count = result.scalar()

        if table_count < 4:
            return {
                "ready": False,
                "reason": "Database schema not fully initialized",
                "timestamp": datetime.utcnow().isoformat() + "Z"
            }

        return {
            "ready": True,
            "timestamp": datetime.utcnow().isoformat() + "Z"
        }
    except Exception as e:
        logger.error(f"Readiness check failed: {e}")
        return {
            "ready": False,
            "reason": str(e),
            "timestamp": datetime.utcnow().isoformat() + "Z"
        }


@router.get("/status/site/{site_id}", response_model=SiteStatusResponse)
async def get_site_status(site_id: str, db: Session = Depends(get_db)):
    """
    Get detailed status for a specific site.

    Includes:
    - Flow ingestion health (receiving, stale, no_data)
    - Learning mode progress and phase
    - Active alerts count (suppressed during learning)
    - Model training status
    - Warnings for potential issues
    """
    status_service = SystemStatusService(db)
    status = status_service.get_site_status(site_id)

    return SiteStatusResponse(
        site_id=status.site_id,
        site_name=status.site_name,
        flow_status=status.flow_status.value,
        last_flow_received=status.last_flow_received.isoformat() + "Z" if status.last_flow_received else None,
        flows_last_hour=status.flows_last_hour,
        flows_last_5min=status.flows_last_5min,
        flows_last_24h=status.flows_last_24h,
        bytes_last_24h=status.bytes_last_24h,
        learning=LearningStatusResponse(
            is_learning=status.learning.is_learning,
            phase=status.learning.phase.value,
            progress_days=status.learning.progress_days,
            target_days=status.learning.target_days,
            progress_percent=status.learning.progress_percent,
            estimated_completion=status.learning.estimated_completion.isoformat() + "Z" if status.learning.estimated_completion else None,
            data_quality=status.learning.data_quality,
            current_assets=status.learning.current_assets,
            min_assets_for_training=status.learning.min_assets_for_training,
            can_transition=status.learning.can_transition,
            alerts_suppressed=status.learning.alerts_suppressed,
            message=status.learning.message,
        ),
        active_alerts=status.active_alerts,
        last_anomaly_score=status.last_anomaly_score,
        model_trained=status.model_trained,
        model_last_trained=status.model_last_trained.isoformat() + "Z" if status.model_last_trained else None,
        last_check=status.last_check.isoformat() + "Z",
        error_message=status.error_message,
        warnings=status.warnings
    )


@router.get("/status/sites")
async def get_all_sites_status(db: Session = Depends(get_db)):
    """Get status for all sites."""
    status_service = SystemStatusService(db)
    statuses = status_service.get_all_sites_status()

    return {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "sites": {
            site_id: {
                "flow_status": s.flow_status.value,
                "last_flow_received": s.last_flow_received.isoformat() + "Z" if s.last_flow_received else None,
                "flows_last_hour": s.flows_last_hour,
                "learning_mode": s.learning_mode,
                "active_alerts": s.active_alerts
            }
            for site_id, s in statuses.items()
        }
    }
