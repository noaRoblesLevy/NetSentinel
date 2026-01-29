"""Dashboard endpoints."""

import logging
from datetime import datetime, timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User
from app.api.v1.endpoints.auth import require_viewer

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/stats")
def get_dashboard_stats(
    site_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_viewer)
):
    """Get dashboard statistics for the frontend."""
    try:
        # Get alert counts
        alert_result = db.execute(
            text("""
                SELECT
                    COUNT(*) FILTER (WHERE status = 'open') as active_alerts,
                    COUNT(*) FILTER (WHERE status = 'open' AND severity = 'critical') as critical_alerts,
                    COUNT(*) FILTER (WHERE status = 'open' AND severity = 'high') as high_alerts
                FROM alerts
                WHERE site_id = :site_id
            """),
            {"site_id": str(site_id)}
        )
        alert_row = alert_result.fetchone()

        # Get asset count
        asset_result = db.execute(
            text("SELECT COUNT(*) as total FROM assets WHERE site_id = :site_id"),
            {"site_id": str(site_id)}
        )
        asset_row = asset_result.fetchone()

        # Get real flow stats from flows_raw table
        flow_result = db.execute(
            text("""
                SELECT
                    COUNT(*) as flows_24h,
                    COALESCE(SUM(bytes), 0) as bytes_24h
                FROM flows_raw
                WHERE site_id = :site_id
                AND ts_start > NOW() - INTERVAL '24 hours'
            """),
            {"site_id": str(site_id)}
        )
        flow_row = flow_result.fetchone()

        return {
            "active_alerts": alert_row.active_alerts or 0,
            "critical_alerts": alert_row.critical_alerts or 0,
            "high_alerts": alert_row.high_alerts or 0,
            "total_assets": asset_row.total or 0,
            "flows_24h": flow_row.flows_24h or 0,
            "bytes_24h": flow_row.bytes_24h or 0,
            "anomalies_24h": 0  # Will be calculated when ML is active
        }
    except Exception as e:
        logger.error(f"Failed to get dashboard stats: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve dashboard statistics")


@router.get("/flows/timeseries")
def get_flow_timeseries(
    site_id: UUID,
    hours: int = 24,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_viewer)
):
    """Get flow time series for charts."""
    try:
        # Query real flow data from flows_raw table, grouped by hour
        # Use inet network containment operators for private IP ranges
        result = db.execute(
            text("""
                SELECT
                    time_bucket('1 hour', ts_start) as hour,
                    COUNT(*) FILTER (WHERE src_ip << '192.168.0.0/16'::inet OR src_ip << '10.0.0.0/8'::inet OR src_ip << '172.16.0.0/12'::inet) as flows_out,
                    COUNT(*) FILTER (WHERE dst_ip << '192.168.0.0/16'::inet OR dst_ip << '10.0.0.0/8'::inet OR dst_ip << '172.16.0.0/12'::inet) as flows_in,
                    COALESCE(SUM(bytes) FILTER (WHERE src_ip << '192.168.0.0/16'::inet OR src_ip << '10.0.0.0/8'::inet OR src_ip << '172.16.0.0/12'::inet), 0) as bytes_out,
                    COALESCE(SUM(bytes) FILTER (WHERE dst_ip << '192.168.0.0/16'::inet OR dst_ip << '10.0.0.0/8'::inet OR dst_ip << '172.16.0.0/12'::inet), 0) as bytes_in
                FROM flows_raw
                WHERE site_id = :site_id
                AND ts_start > NOW() - make_interval(hours => :hours)
                GROUP BY hour
                ORDER BY hour ASC
            """),
            {"site_id": str(site_id), "hours": hours}
        )

        data = []
        for row in result:
            data.append({
                "timestamp": row.hour.isoformat() + "Z",
                "flows_in": row.flows_in or 0,
                "flows_out": row.flows_out or 0,
                "bytes_in": row.bytes_in or 0,
                "bytes_out": row.bytes_out or 0,
            })

        # If no data, return empty slots for the time range
        if not data:
            now = datetime.utcnow()
            for i in range(hours, 0, -1):
                ts = now - timedelta(hours=i)
                data.append({
                    "timestamp": ts.isoformat() + "Z",
                    "flows_in": 0,
                    "flows_out": 0,
                    "bytes_in": 0,
                    "bytes_out": 0,
                })

        return data
    except Exception as e:
        logger.error(f"Failed to get flow timeseries: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve flow timeseries data")


@router.get("/anomalies/timeseries")
def get_anomaly_timeseries(
    site_id: UUID,
    hours: int = 24,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_viewer)
):
    """Get anomaly score time series based on alert counts per hour."""
    try:
        # Calculate anomaly scores based on alert creation patterns
        result = db.execute(
            text("""
                SELECT
                    time_bucket('1 hour', created_at) as hour,
                    COUNT(*) as alert_count,
                    COUNT(*) FILTER (WHERE severity = 'critical') as critical_count,
                    COUNT(*) FILTER (WHERE severity = 'high') as high_count
                FROM alerts
                WHERE site_id = :site_id
                AND created_at > NOW() - make_interval(hours => :hours)
                GROUP BY hour
                ORDER BY hour ASC
            """),
            {"site_id": str(site_id), "hours": hours}
        )

        # Build a map of hours to scores
        hour_scores = {}
        for row in result:
            # Calculate score based on alert severity weights
            score = min(1.0, (row.critical_count * 0.4 + row.high_count * 0.2 + row.alert_count * 0.05))
            hour_scores[row.hour.replace(minute=0, second=0, microsecond=0)] = round(score, 3)

        # Generate data for all hours in the range
        data = []
        now = datetime.utcnow().replace(minute=0, second=0, microsecond=0)
        for i in range(hours, 0, -1):
            ts = now - timedelta(hours=i)
            score = hour_scores.get(ts, 0.05)  # Base noise level
            data.append({
                "timestamp": ts.isoformat() + "Z",
                "value": score
            })

        return data
    except Exception as e:
        logger.error(f"Failed to get anomaly timeseries: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve anomaly timeseries data")


@router.get("/overview")
async def get_dashboard_overview(
    site_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_viewer)
):
    """Get dashboard overview statistics."""
    try:
        # Get alert stats
        alert_result = db.execute(
            text("""
                SELECT
                    COUNT(*) FILTER (WHERE status = 'open') as open_total,
                    COUNT(*) FILTER (WHERE status = 'open' AND severity IN ('high', 'critical')) as open_high,
                    COUNT(*) FILTER (WHERE status = 'open' AND severity = 'critical') as open_critical,
                    COUNT(*) FILTER (WHERE created_at > NOW() - INTERVAL '24 hours') as last_24h
                FROM alerts
                WHERE site_id = :site_id
            """),
            {"site_id": str(site_id)}
        )
        alert_row = alert_result.fetchone()

        # Get device stats
        device_result = db.execute(
            text("""
                SELECT
                    COUNT(*) FILTER (WHERE is_monitored = true) as total_monitored,
                    COUNT(*) FILTER (WHERE last_seen > NOW() - INTERVAL '1 hour') as active_last_hour,
                    COUNT(*) FILTER (WHERE first_seen > NOW() - INTERVAL '24 hours') as new_last_24h
                FROM assets
                WHERE site_id = :site_id
            """),
            {"site_id": str(site_id)}
        )
        device_row = device_result.fetchone()

        # Get traffic stats
        traffic_result = db.execute(
            text("""
                SELECT
                    COUNT(*) as flows_last_hour,
                    COALESCE(SUM(bytes), 0) as bytes_last_hour
                FROM flows_raw
                WHERE site_id = :site_id
                AND ts_start > NOW() - INTERVAL '1 hour'
            """),
            {"site_id": str(site_id)}
        )
        traffic_row = traffic_result.fetchone()

        # Get site status
        site_result = db.execute(
            text("SELECT status FROM sites WHERE id = :site_id"),
            {"site_id": str(site_id)}
        )
        site_row = site_result.fetchone()

        return {
            "site_id": str(site_id),
            "site_status": site_row.status if site_row else "unknown",
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "alerts": {
                "open_total": alert_row.open_total or 0,
                "open_high": alert_row.open_high or 0,
                "open_critical": alert_row.open_critical or 0,
                "last_24h": alert_row.last_24h or 0
            },
            "devices": {
                "total_monitored": device_row.total_monitored or 0,
                "active_last_hour": device_row.active_last_hour or 0,
                "new_last_24h": device_row.new_last_24h or 0
            },
            "traffic": {
                "flows_last_hour": traffic_row.flows_last_hour or 0,
                "bytes_last_hour": traffic_row.bytes_last_hour or 0
            }
        }

    except Exception as e:
        logger.error(f"Failed to get dashboard overview: {e}")
        raise HTTPException(
            status_code=500,
            detail="Failed to retrieve dashboard overview"
        )


@router.get("/traffic-chart")
async def get_traffic_chart(
    site_id: UUID,
    hours: int = 24,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_viewer)
):
    """Get traffic time-series for charts."""
    try:
        result = db.execute(
            text("""
                SELECT
                    time_bucket('1 hour', ts_start) as hour,
                    COUNT(*) as flows,
                    COALESCE(SUM(bytes), 0) as bytes,
                    COALESCE(SUM(packets), 0) as packets,
                    COUNT(DISTINCT src_ip) as unique_src_ips,
                    COUNT(DISTINCT dst_ip) as unique_dst_ips
                FROM flows_raw
                WHERE site_id = :site_id
                AND ts_start > NOW() - make_interval(hours => :hours)
                GROUP BY hour
                ORDER BY hour DESC
            """),
            {"site_id": str(site_id), "hours": hours}
        )

        data = []
        for row in result:
            data.append({
                "timestamp": row.hour.isoformat() + "Z",
                "flows": row.flows,
                "bytes": row.bytes,
                "packets": row.packets,
                "unique_src_ips": row.unique_src_ips,
                "unique_dst_ips": row.unique_dst_ips
            })

        return {
            "site_id": str(site_id),
            "resolution": "1h",
            "data": data
        }

    except Exception as e:
        logger.error(f"Failed to get traffic chart: {e}")
        raise HTTPException(
            status_code=500,
            detail="Failed to retrieve traffic chart data"
        )
