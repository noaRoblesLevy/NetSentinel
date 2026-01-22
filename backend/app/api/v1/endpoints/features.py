"""
Features API endpoints - query aggregated feature vectors.
"""

from datetime import datetime, timedelta
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User
from app.api.v1.endpoints.auth import require_viewer, require_analyst

router = APIRouter()


class FeatureVector(BaseModel):
    """5-minute feature vector for an asset."""

    window_start: datetime
    window_end: datetime
    site_id: UUID
    asset_id: UUID
    asset_ip: Optional[str] = None

    # Traffic volume
    flows_in: int = 0
    flows_out: int = 0
    bytes_in: int = 0
    bytes_out: int = 0
    packets_in: int = 0
    packets_out: int = 0

    # Connection diversity
    unique_src_ips: int = 0
    unique_dst_ips: int = 0
    unique_src_ports: int = 0
    unique_dst_ports: int = 0

    # Internal/external breakdown
    internal_dst_count: int = 0
    external_dst_count: int = 0
    internal_src_count: int = 0
    external_src_count: int = 0

    # Entropy features (anomaly indicators)
    dst_port_entropy: float = 0.0
    dst_ip_entropy: float = 0.0
    src_port_entropy: float = 0.0

    # Protocol breakdown
    tcp_flows: int = 0
    udp_flows: int = 0
    icmp_flows: int = 0
    other_protocol_flows: int = 0

    # Averages
    avg_bytes_per_flow: float = 0.0
    avg_packets_per_flow: float = 0.0

    # Time context
    hour_of_day: int = 0
    day_of_week: int = 0
    is_business_hours: bool = False

    # Ratios
    internal_external_ratio: float = 0.5

    class Config:
        from_attributes = True


class FeatureStats(BaseModel):
    """Aggregated statistics for feature vectors."""

    site_id: UUID
    window_count: int
    asset_count: int
    total_flows: int
    total_bytes: int
    avg_dst_port_entropy: float
    avg_dst_ip_entropy: float
    max_dst_port_entropy: float
    max_dst_ip_entropy: float


class TriggerResponse(BaseModel):
    """Response for manual aggregation trigger."""

    status: str
    task_id: str
    window_start: str


@router.get("", response_model=List[FeatureVector])
async def list_features(
    site_id: UUID = Query(..., description="Site ID to query"),
    asset_id: Optional[UUID] = Query(None, description="Filter by asset ID"),
    start_time: Optional[datetime] = Query(None, description="Start of time range"),
    end_time: Optional[datetime] = Query(None, description="End of time range"),
    min_entropy: Optional[float] = Query(None, description="Minimum dst_port_entropy"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_viewer),
):
    """
    List feature vectors for a site.

    Filter by time range, asset, or minimum entropy to find anomalies.
    """
    # Default to last 24 hours
    if not end_time:
        end_time = datetime.utcnow()
    if not start_time:
        start_time = end_time - timedelta(hours=24)

    query = """
        SELECT
            f.window_start, f.window_end, f.site_id, f.asset_id,
            a.ip::text as asset_ip,
            f.flows_in, f.flows_out, f.bytes_in, f.bytes_out,
            f.packets_in, f.packets_out,
            f.unique_src_ips, f.unique_dst_ips,
            f.unique_src_ports, f.unique_dst_ports,
            f.internal_dst_count, f.external_dst_count,
            f.internal_src_count, f.external_src_count,
            f.dst_port_entropy, f.dst_ip_entropy, f.src_port_entropy,
            f.tcp_flows, f.udp_flows, f.icmp_flows, f.other_protocol_flows,
            f.avg_bytes_per_flow, f.avg_packets_per_flow,
            f.hour_of_day, f.day_of_week, f.is_business_hours,
            f.internal_external_ratio
        FROM features_5m f
        JOIN assets a ON f.asset_id = a.id
        WHERE f.site_id = :site_id
        AND f.window_start >= :start_time
        AND f.window_start < :end_time
    """

    params = {
        "site_id": str(site_id),
        "start_time": start_time,
        "end_time": end_time,
    }

    if asset_id:
        query += " AND f.asset_id = :asset_id"
        params["asset_id"] = str(asset_id)

    if min_entropy is not None:
        query += " AND f.dst_port_entropy >= :min_entropy"
        params["min_entropy"] = min_entropy

    query += " ORDER BY f.window_start DESC LIMIT :limit OFFSET :offset"
    params["limit"] = limit
    params["offset"] = offset

    result = db.execute(text(query), params)
    rows = result.fetchall()

    return [FeatureVector(**dict(row._mapping)) for row in rows]


@router.get("/stats", response_model=FeatureStats)
async def get_feature_stats(
    site_id: UUID = Query(..., description="Site ID to query"),
    start_time: Optional[datetime] = Query(None, description="Start of time range"),
    end_time: Optional[datetime] = Query(None, description="End of time range"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_viewer),
):
    """
    Get aggregated statistics for feature vectors.

    Useful for understanding baseline behavior and detecting anomalies.
    """
    if not end_time:
        end_time = datetime.utcnow()
    if not start_time:
        start_time = end_time - timedelta(hours=24)

    result = db.execute(
        text("""
            SELECT
                :site_id as site_id,
                COUNT(DISTINCT window_start) as window_count,
                COUNT(DISTINCT asset_id) as asset_count,
                COALESCE(SUM(flows_in + flows_out), 0) as total_flows,
                COALESCE(SUM(bytes_in + bytes_out), 0) as total_bytes,
                COALESCE(AVG(dst_port_entropy), 0) as avg_dst_port_entropy,
                COALESCE(AVG(dst_ip_entropy), 0) as avg_dst_ip_entropy,
                COALESCE(MAX(dst_port_entropy), 0) as max_dst_port_entropy,
                COALESCE(MAX(dst_ip_entropy), 0) as max_dst_ip_entropy
            FROM features_5m
            WHERE site_id = :site_id
            AND window_start >= :start_time
            AND window_start < :end_time
        """),
        {"site_id": str(site_id), "start_time": start_time, "end_time": end_time}
    )

    row = result.fetchone()
    return FeatureStats(**dict(row._mapping))


@router.get("/high-entropy", response_model=List[FeatureVector])
async def get_high_entropy_features(
    site_id: UUID = Query(..., description="Site ID to query"),
    threshold: float = Query(3.0, description="Entropy threshold"),
    hours: int = Query(24, ge=1, le=168, description="Hours to look back"),
    limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_viewer),
):
    """
    Get feature vectors with high entropy (potential anomalies).

    High destination port entropy may indicate port scanning.
    High destination IP entropy may indicate reconnaissance.
    """
    end_time = datetime.utcnow()
    start_time = end_time - timedelta(hours=hours)

    result = db.execute(
        text("""
            SELECT
                f.window_start, f.window_end, f.site_id, f.asset_id,
                a.ip::text as asset_ip,
                f.flows_in, f.flows_out, f.bytes_in, f.bytes_out,
                f.packets_in, f.packets_out,
                f.unique_src_ips, f.unique_dst_ips,
                f.unique_src_ports, f.unique_dst_ports,
                f.internal_dst_count, f.external_dst_count,
                f.internal_src_count, f.external_src_count,
                f.dst_port_entropy, f.dst_ip_entropy, f.src_port_entropy,
                f.tcp_flows, f.udp_flows, f.icmp_flows, f.other_protocol_flows,
                f.avg_bytes_per_flow, f.avg_packets_per_flow,
                f.hour_of_day, f.day_of_week, f.is_business_hours,
                f.internal_external_ratio
            FROM features_5m f
            JOIN assets a ON f.asset_id = a.id
            WHERE f.site_id = :site_id
            AND f.window_start >= :start_time
            AND f.window_start < :end_time
            AND (f.dst_port_entropy >= :threshold OR f.dst_ip_entropy >= :threshold)
            ORDER BY GREATEST(f.dst_port_entropy, f.dst_ip_entropy) DESC
            LIMIT :limit
        """),
        {
            "site_id": str(site_id),
            "start_time": start_time,
            "end_time": end_time,
            "threshold": threshold,
            "limit": limit,
        }
    )

    rows = result.fetchall()
    return [FeatureVector(**dict(row._mapping)) for row in rows]


@router.post("/trigger", response_model=TriggerResponse)
async def trigger_aggregation(
    site_id: Optional[UUID] = Query(None, description="Specific site to aggregate"),
    window_start: Optional[datetime] = Query(None, description="Specific window to process"),
    current_user: User = Depends(require_analyst),
):
    """
    Manually trigger the aggregation job.

    Useful for backfilling or reprocessing specific windows.
    """
    from app.workers.aggregation import aggregate_flows

    # Trigger the Celery task
    task = aggregate_flows.delay(
        site_id=str(site_id) if site_id else None,
        window_start=window_start.isoformat() if window_start else None,
    )

    return TriggerResponse(
        status="queued",
        task_id=task.id,
        window_start=window_start.isoformat() if window_start else "latest",
    )


@router.get("/asset/{asset_id}/timeline", response_model=List[FeatureVector])
async def get_asset_timeline(
    asset_id: UUID,
    hours: int = Query(24, ge=1, le=168, description="Hours to look back"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_viewer),
):
    """
    Get feature vector timeline for a specific asset.

    Useful for investigating suspicious assets or understanding behavior patterns.
    """
    end_time = datetime.utcnow()
    start_time = end_time - timedelta(hours=hours)

    result = db.execute(
        text("""
            SELECT
                f.window_start, f.window_end, f.site_id, f.asset_id,
                a.ip::text as asset_ip,
                f.flows_in, f.flows_out, f.bytes_in, f.bytes_out,
                f.packets_in, f.packets_out,
                f.unique_src_ips, f.unique_dst_ips,
                f.unique_src_ports, f.unique_dst_ports,
                f.internal_dst_count, f.external_dst_count,
                f.internal_src_count, f.external_src_count,
                f.dst_port_entropy, f.dst_ip_entropy, f.src_port_entropy,
                f.tcp_flows, f.udp_flows, f.icmp_flows, f.other_protocol_flows,
                f.avg_bytes_per_flow, f.avg_packets_per_flow,
                f.hour_of_day, f.day_of_week, f.is_business_hours,
                f.internal_external_ratio
            FROM features_5m f
            JOIN assets a ON f.asset_id = a.id
            WHERE f.asset_id = :asset_id
            AND f.window_start >= :start_time
            AND f.window_start < :end_time
            ORDER BY f.window_start ASC
        """),
        {"asset_id": str(asset_id), "start_time": start_time, "end_time": end_time}
    )

    rows = result.fetchall()
    return [FeatureVector(**dict(row._mapping)) for row in rows]
