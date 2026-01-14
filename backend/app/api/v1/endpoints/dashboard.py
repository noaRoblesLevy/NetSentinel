"""Dashboard endpoints."""

import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database import get_db

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/overview")
async def get_dashboard_overview(
    site_id: str,
    db: Session = Depends(get_db)
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
            {"site_id": site_id}
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
            {"site_id": site_id}
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
            {"site_id": site_id}
        )
        traffic_row = traffic_result.fetchone()

        # Get site status
        site_result = db.execute(
            text("SELECT status FROM sites WHERE id = :site_id"),
            {"site_id": site_id}
        )
        site_row = site_result.fetchone()

        return {
            "site_id": site_id,
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
            detail=str(e)
        )


@router.get("/traffic-chart")
async def get_traffic_chart(
    site_id: str,
    hours: int = 24,
    db: Session = Depends(get_db)
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
                AND ts_start > NOW() - INTERVAL ':hours hours'
                GROUP BY hour
                ORDER BY hour DESC
            """.replace(":hours", str(hours))),
            {"site_id": site_id}
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
            "site_id": site_id,
            "resolution": "1h",
            "data": data
        }

    except Exception as e:
        logger.error(f"Failed to get traffic chart: {e}")
        raise HTTPException(
            status_code=500,
            detail=str(e)
        )
