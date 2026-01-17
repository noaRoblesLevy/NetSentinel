"""System status tracking for flow ingestion, learning mode, and component health."""

import logging
from datetime import datetime, timedelta
from enum import Enum
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


class HealthStatus(str, Enum):
    """Health status levels."""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


class FlowStatus(str, Enum):
    """Flow ingestion status."""
    UNKNOWN = "unknown"
    RECEIVING = "receiving"
    NO_DATA = "no_data"
    STALE = "stale"
    ERROR = "error"


class LearningPhase(str, Enum):
    """Learning mode phases."""
    NOT_STARTED = "not_started"
    COLLECTING = "collecting"
    TRAINING = "training"
    COMPLETE = "complete"


@dataclass
class LearningStatus:
    """Learning mode status for a site."""
    is_learning: bool = True
    phase: LearningPhase = LearningPhase.NOT_STARTED
    progress_days: int = 0
    target_days: int = 7
    progress_percent: float = 0.0
    estimated_completion: Optional[datetime] = None
    data_quality: str = "unknown"  # insufficient, poor, fair, good
    min_assets_for_training: int = 5
    current_assets: int = 0
    can_transition: bool = False
    alerts_suppressed: bool = True
    message: str = "Waiting for data collection to begin"


@dataclass
class SiteStatus:
    """Status information for a site."""
    site_id: str
    site_name: str = ""
    flow_status: FlowStatus = FlowStatus.UNKNOWN
    last_flow_received: Optional[datetime] = None
    flows_last_hour: int = 0
    flows_last_5min: int = 0
    flows_last_24h: int = 0
    bytes_last_24h: int = 0
    learning: LearningStatus = field(default_factory=LearningStatus)
    active_alerts: int = 0
    last_anomaly_score: Optional[float] = None
    model_trained: bool = False
    model_last_trained: Optional[datetime] = None
    last_check: datetime = field(default_factory=datetime.utcnow)
    error_message: Optional[str] = None
    warnings: List[str] = field(default_factory=list)


@dataclass
class ComponentHealth:
    """Health status for a system component."""
    name: str
    status: HealthStatus = HealthStatus.UNKNOWN
    last_check: datetime = field(default_factory=datetime.utcnow)
    message: Optional[str] = None
    metrics: Dict[str, Any] = field(default_factory=dict)


class SystemStatusService:
    """Service for tracking system-wide status and health."""

    # Thresholds for flow status determination
    FLOW_STALE_MINUTES = 10  # No flows for 10 min = stale
    FLOW_NO_DATA_MINUTES = 30  # No flows for 30 min = no_data
    MIN_FLOWS_PER_HOUR = 10  # Minimum expected flows per hour

    def __init__(self, db: Session):
        self.db = db
        self._component_status: Dict[str, ComponentHealth] = {}

    def get_site_status(self, site_id: str) -> SiteStatus:
        """Get comprehensive status for a site including learning mode details."""
        status = SiteStatus(site_id=site_id)

        try:
            # Get site info
            result = self.db.execute(
                text("""
                    SELECT name, status, created_at, config
                    FROM sites
                    WHERE id = :site_id
                """),
                {"site_id": site_id}
            )
            site_row = result.fetchone()
            if not site_row:
                status.error_message = "Site not found"
                return status

            status.site_name = site_row.name or ""
            site_status = site_row.status
            site_created = site_row.created_at
            config = site_row.config or {}
            learning_days = config.get('learning_days', 7)

            # Get flow statistics
            result = self.db.execute(
                text("""
                    SELECT
                        MAX(ts_end) as last_flow,
                        COUNT(*) FILTER (WHERE ts_start > NOW() - INTERVAL '5 minutes') as last_5min,
                        COUNT(*) FILTER (WHERE ts_start > NOW() - INTERVAL '1 hour') as last_hour,
                        COUNT(*) FILTER (WHERE ts_start > NOW() - INTERVAL '24 hours') as last_24h,
                        COALESCE(SUM(bytes) FILTER (WHERE ts_start > NOW() - INTERVAL '24 hours'), 0) as bytes_24h
                    FROM flows_raw
                    WHERE site_id = :site_id
                """),
                {"site_id": site_id}
            )
            row = result.fetchone()
            if row:
                status.last_flow_received = row.last_flow
                status.flows_last_5min = row.last_5min or 0
                status.flows_last_hour = row.last_hour or 0
                status.flows_last_24h = row.last_24h or 0
                status.bytes_last_24h = row.bytes_24h or 0

            # Determine flow status
            status.flow_status = self._determine_flow_status(status)

            # Get asset count
            result = self.db.execute(
                text("SELECT COUNT(*) FROM assets WHERE site_id = :site_id"),
                {"site_id": site_id}
            )
            asset_count = result.scalar() or 0

            # Check for trained model
            result = self.db.execute(
                text("""
                    SELECT id, created_at
                    FROM baseline_models
                    WHERE site_id = :site_id AND is_active = true
                    ORDER BY created_at DESC
                    LIMIT 1
                """),
                {"site_id": site_id}
            )
            model_row = result.fetchone()
            status.model_trained = model_row is not None
            status.model_last_trained = model_row.created_at if model_row else None

            # Calculate learning status
            status.learning = self._calculate_learning_status(
                site_status=site_status,
                site_created=site_created,
                learning_days=learning_days,
                asset_count=asset_count,
                flows_24h=status.flows_last_24h,
                model_trained=status.model_trained,
                flow_status=status.flow_status
            )

            # Get active alert count (only if not in learning mode)
            if not status.learning.is_learning:
                result = self.db.execute(
                    text("""
                        SELECT COUNT(*) as count
                        FROM alerts
                        WHERE site_id = :site_id AND status = 'open'
                    """),
                    {"site_id": site_id}
                )
                row = result.fetchone()
                status.active_alerts = row.count if row else 0
            else:
                status.active_alerts = 0  # Suppressed during learning

            # Get latest anomaly score
            result = self.db.execute(
                text("""
                    SELECT anomaly_score
                    FROM anomaly_scores_5m
                    WHERE site_id = :site_id
                    ORDER BY window_start DESC
                    LIMIT 1
                """),
                {"site_id": site_id}
            )
            row = result.fetchone()
            status.last_anomaly_score = row.anomaly_score if row else None

            # Add warnings for potential issues
            if status.flow_status == FlowStatus.STALE:
                status.warnings.append("Flow data is stale - check collector connection")
            if status.flow_status == FlowStatus.NO_DATA:
                status.warnings.append("No flow data received - verify network configuration")
            if status.learning.is_learning and status.learning.data_quality == "insufficient":
                status.warnings.append("Insufficient data for reliable detection")

        except Exception as e:
            logger.error(f"Error getting site status: {e}")
            status.flow_status = FlowStatus.ERROR
            status.error_message = str(e)

        status.last_check = datetime.utcnow()
        return status

    def _calculate_learning_status(
        self,
        site_status: str,
        site_created: Optional[datetime],
        learning_days: int,
        asset_count: int,
        flows_24h: int,
        model_trained: bool,
        flow_status: FlowStatus
    ) -> LearningStatus:
        """Calculate detailed learning mode status."""
        learning = LearningStatus(target_days=learning_days)
        learning.current_assets = asset_count
        learning.min_assets_for_training = 5

        # Check if learning is complete
        if site_status == 'active' and model_trained:
            learning.is_learning = False
            learning.phase = LearningPhase.COMPLETE
            learning.progress_percent = 100.0
            learning.alerts_suppressed = False
            learning.can_transition = True
            learning.message = "Detection active - monitoring for anomalies"
            return learning

        # Still in learning mode
        learning.is_learning = True
        learning.alerts_suppressed = True

        if not site_created:
            learning.phase = LearningPhase.NOT_STARTED
            learning.message = "Site not configured"
            return learning

        # Calculate progress
        now = datetime.utcnow()
        days_elapsed = (now - site_created).days
        learning.progress_days = min(days_elapsed, learning_days)
        learning.progress_percent = min(100.0, (days_elapsed / learning_days) * 100)

        if days_elapsed < learning_days:
            remaining_days = learning_days - days_elapsed
            learning.estimated_completion = now + timedelta(days=remaining_days)

        # Determine phase and data quality
        if flow_status == FlowStatus.NO_DATA:
            learning.phase = LearningPhase.NOT_STARTED
            learning.data_quality = "insufficient"
            learning.message = "Waiting for flow data - connect your network devices"
        elif flow_status == FlowStatus.STALE:
            learning.phase = LearningPhase.COLLECTING
            learning.data_quality = "poor"
            learning.message = f"Data collection paused - Day {learning.progress_days} of {learning_days}"
        elif days_elapsed < 1:
            learning.phase = LearningPhase.COLLECTING
            learning.data_quality = "insufficient"
            learning.message = "Initial data collection - building baseline"
        elif days_elapsed < 3:
            learning.phase = LearningPhase.COLLECTING
            learning.data_quality = "poor" if flows_24h < 1000 else "fair"
            learning.message = f"Day {learning.progress_days} of {learning_days} - learning normal patterns"
        elif days_elapsed < learning_days:
            learning.phase = LearningPhase.COLLECTING
            learning.data_quality = "fair" if flows_24h < 5000 else "good"
            learning.message = f"Day {learning.progress_days} of {learning_days} - refining baseline"
        else:
            learning.phase = LearningPhase.TRAINING
            learning.data_quality = "good" if flows_24h >= 1000 and asset_count >= 5 else "fair"
            learning.can_transition = asset_count >= learning.min_assets_for_training
            if learning.can_transition:
                learning.message = "Ready to transition to active detection"
            else:
                learning.message = f"Need at least {learning.min_assets_for_training} assets (have {asset_count})"

        return learning

    def _determine_flow_status(self, status: SiteStatus) -> FlowStatus:
        """Determine flow status based on timestamps and counts."""
        if status.last_flow_received is None:
            return FlowStatus.NO_DATA

        now = datetime.utcnow()
        # Handle timezone-aware datetimes
        last_flow = status.last_flow_received
        if last_flow.tzinfo is not None:
            last_flow = last_flow.replace(tzinfo=None)

        minutes_since_last = (now - last_flow).total_seconds() / 60

        if minutes_since_last > self.FLOW_NO_DATA_MINUTES:
            return FlowStatus.NO_DATA
        elif minutes_since_last > self.FLOW_STALE_MINUTES:
            return FlowStatus.STALE
        elif status.flows_last_5min > 0:
            return FlowStatus.RECEIVING
        else:
            return FlowStatus.STALE

    def get_all_sites_status(self) -> Dict[str, SiteStatus]:
        """Get status for all sites."""
        statuses = {}
        try:
            result = self.db.execute(text("SELECT id FROM sites"))
            for row in result:
                site_id = str(row.id)
                statuses[site_id] = self.get_site_status(site_id)
        except Exception as e:
            logger.error(f"Error getting all sites status: {e}")
        return statuses

    def check_component_health(self, name: str, check_fn) -> ComponentHealth:
        """Check and record health of a system component."""
        health = ComponentHealth(name=name)
        try:
            result = check_fn()
            health.status = HealthStatus.HEALTHY
            health.metrics = result if isinstance(result, dict) else {}
        except Exception as e:
            health.status = HealthStatus.UNHEALTHY
            health.message = str(e)
            logger.error(f"Component {name} unhealthy: {e}")

        health.last_check = datetime.utcnow()
        self._component_status[name] = health
        return health

    def check_database_health(self) -> ComponentHealth:
        """Check database connectivity and performance."""
        def check():
            start = datetime.utcnow()
            self.db.execute(text("SELECT 1"))
            latency_ms = (datetime.utcnow() - start).total_seconds() * 1000
            return {"latency_ms": latency_ms, "connected": True}

        return self.check_component_health("database", check)

    def check_redis_health(self) -> ComponentHealth:
        """Check Redis connectivity."""
        def check():
            from redis import Redis
            from app.config import settings
            r = Redis.from_url(settings.redis_url)
            r.ping()
            return {"connected": True}

        return self.check_component_health("redis", check)

    def get_system_health(self) -> Dict[str, Any]:
        """Get overall system health summary."""
        db_health = self.check_database_health()

        # Determine overall status
        if db_health.status == HealthStatus.UNHEALTHY:
            overall = HealthStatus.UNHEALTHY
        elif db_health.status == HealthStatus.DEGRADED:
            overall = HealthStatus.DEGRADED
        else:
            overall = HealthStatus.HEALTHY

        return {
            "status": overall.value,
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "components": {
                "database": {
                    "status": db_health.status.value,
                    "message": db_health.message,
                    "metrics": db_health.metrics
                }
            }
        }


def record_flow_ingestion_error(db: Session, site_id: str, error_type: str, details: str):
    """Record a flow ingestion error for monitoring."""
    try:
        db.execute(
            text("""
                INSERT INTO ingestion_errors (site_id, error_type, details, created_at)
                VALUES (:site_id, :error_type, :details, NOW())
            """),
            {"site_id": site_id, "error_type": error_type, "details": details[:500]}
        )
        db.commit()
    except Exception as e:
        logger.warning(f"Could not record ingestion error: {e}")
        db.rollback()
