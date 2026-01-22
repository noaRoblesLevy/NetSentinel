"""Flow ingestion endpoints with defensive parsing and error handling."""

import hashlib
import ipaddress
import logging
import re
from datetime import datetime, timedelta
from typing import List, Optional, Tuple
from uuid import uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.models import User
from app.api.v1.endpoints.auth import require_viewer

logger = logging.getLogger(__name__)
settings = get_settings()
router = APIRouter()

# Constants for validation
MAX_FLOW_AGE_HOURS = 24  # Reject flows older than this
MAX_FUTURE_DRIFT_SECONDS = 300  # Allow 5 min clock drift into future
MAX_BATCH_SIZE = 10000  # Maximum flows per batch
MAX_PORT = 65535
MAX_PROTOCOL = 255


class FlowRecord(BaseModel):
    """Single flow record from collector with validation."""
    ts_start: datetime
    ts_end: datetime
    src_ip: str
    dst_ip: str
    src_port: int = Field(default=0, ge=0, le=MAX_PORT)
    dst_port: int = Field(default=0, ge=0, le=MAX_PORT)
    protocol: int = Field(ge=0, le=MAX_PROTOCOL)
    bytes: int = Field(default=0, ge=0)
    packets: int = Field(default=0, ge=0)
    tcp_flags: Optional[int] = Field(default=None, ge=0, le=255)
    duration_ms: Optional[int] = Field(default=None, ge=0)

    @field_validator('src_ip', 'dst_ip')
    @classmethod
    def validate_ip(cls, v: str) -> str:
        """Validate IP address format."""
        try:
            ipaddress.ip_address(v)
            return v
        except ValueError:
            raise ValueError(f"Invalid IP address: {v}")

    @field_validator('ts_end')
    @classmethod
    def validate_ts_end(cls, v: datetime, info) -> datetime:
        """Ensure ts_end >= ts_start."""
        ts_start = info.data.get('ts_start')
        if ts_start and v < ts_start:
            # Swap them if reversed (common exporter bug)
            return ts_start
        return v


class FlowBatch(BaseModel):
    """Batch of flow records with validation."""
    site_id: str = Field(min_length=1, max_length=100)
    exporter_id: str = Field(min_length=1, max_length=100)
    flows: List[FlowRecord] = Field(max_length=MAX_BATCH_SIZE)
    batch_id: Optional[str] = None
    timestamp: Optional[datetime] = None

    @field_validator('site_id', 'exporter_id')
    @classmethod
    def sanitize_identifiers(cls, v: str) -> str:
        """Sanitize identifiers to prevent injection."""
        # Allow only alphanumeric, hyphens, underscores
        if not re.match(r'^[a-zA-Z0-9_-]+$', v):
            raise ValueError(f"Invalid identifier format: {v}")
        return v


class FlowIngestResponse(BaseModel):
    """Response for flow ingestion."""
    status: str
    flows_received: int
    flows_accepted: int
    flows_rejected: int
    batch_id: str
    warnings: List[str] = []


class FlowValidationResult:
    """Result of flow validation."""
    def __init__(self):
        self.valid_flows: List[FlowRecord] = []
        self.rejected_count = 0
        self.warnings: List[str] = []
        self.seen_hashes: set = set()


def compute_flow_hash(flow: FlowRecord, site_id: str) -> str:
    """Compute hash for duplicate detection."""
    key = f"{site_id}:{flow.ts_start.isoformat()}:{flow.src_ip}:{flow.dst_ip}:{flow.src_port}:{flow.dst_port}:{flow.protocol}"
    return hashlib.md5(key.encode()).hexdigest()[:16]


def validate_flow_timing(flow: FlowRecord, now: datetime) -> Tuple[bool, Optional[str]]:
    """Validate flow timestamps for clock drift and age."""
    # Check for future timestamps (clock drift)
    max_future = now + timedelta(seconds=MAX_FUTURE_DRIFT_SECONDS)
    if flow.ts_start > max_future:
        return False, f"Flow timestamp {flow.ts_start} is too far in the future"

    # Check for stale flows
    min_time = now - timedelta(hours=MAX_FLOW_AGE_HOURS)
    if flow.ts_end < min_time:
        return False, f"Flow timestamp {flow.ts_end} is too old (>{MAX_FLOW_AGE_HOURS}h)"

    return True, None


def validate_and_filter_flows(
    batch: FlowBatch,
    now: datetime
) -> FlowValidationResult:
    """Validate flows and filter out invalid/duplicate ones."""
    result = FlowValidationResult()

    for flow in batch.flows:
        # Check timing
        valid, warning = validate_flow_timing(flow, now)
        if not valid:
            result.rejected_count += 1
            if len(result.warnings) < 5:  # Limit warnings
                result.warnings.append(warning)
            continue

        # Check for duplicates within batch
        flow_hash = compute_flow_hash(flow, batch.site_id)
        if flow_hash in result.seen_hashes:
            result.rejected_count += 1
            continue
        result.seen_hashes.add(flow_hash)

        result.valid_flows.append(flow)

    if result.rejected_count > 0:
        result.warnings.insert(0, f"Rejected {result.rejected_count} flows (timing/duplicate)")

    return result


@router.post("/ingest", response_model=FlowIngestResponse, status_code=status.HTTP_202_ACCEPTED)
async def ingest_flows(
    batch: FlowBatch,
    db: Session = Depends(get_db),
    x_collector_key: Optional[str] = Header(None)
):
    """
    Receive flow records from the collector.

    This endpoint receives batches of normalized flow records from the
    Go collector and inserts them into the flows_raw table.

    Features:
    - Validates IP addresses and port numbers
    - Rejects flows with future timestamps (clock drift protection)
    - Rejects stale flows (>24h old)
    - Deduplicates flows within batch
    - Uses parameterized queries (SQL injection protection)
    """
    # Validate collector API key
    if settings.collector_api_key and x_collector_key != settings.collector_api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid collector API key"
        )

    batch_id = batch.batch_id or str(uuid4())
    now = datetime.utcnow()

    if not batch.flows:
        return FlowIngestResponse(
            status="accepted",
            flows_received=0,
            flows_accepted=0,
            flows_rejected=0,
            batch_id=batch_id
        )

    # Validate and filter flows
    validation = validate_and_filter_flows(batch, now)

    if not validation.valid_flows:
        return FlowIngestResponse(
            status="accepted",
            flows_received=len(batch.flows),
            flows_accepted=0,
            flows_rejected=validation.rejected_count,
            batch_id=batch_id,
            warnings=validation.warnings
        )

    try:
        # Use parameterized bulk insert (safe from SQL injection)
        for flow in validation.valid_flows:
            db.execute(
                text("""
                    INSERT INTO flows_raw (
                        ts_start, ts_end, site_id, exporter_id,
                        src_ip, dst_ip, src_port, dst_port,
                        protocol, bytes, packets, duration_ms, tcp_flags
                    ) VALUES (
                        :ts_start, :ts_end, :site_id, :exporter_id,
                        :src_ip, :dst_ip, :src_port, :dst_port,
                        :protocol, :bytes, :packets, :duration_ms, :tcp_flags
                    )
                    ON CONFLICT DO NOTHING
                """),
                {
                    "ts_start": flow.ts_start,
                    "ts_end": flow.ts_end,
                    "site_id": batch.site_id,
                    "exporter_id": batch.exporter_id,
                    "src_ip": flow.src_ip,
                    "dst_ip": flow.dst_ip,
                    "src_port": flow.src_port,
                    "dst_port": flow.dst_port,
                    "protocol": flow.protocol,
                    "bytes": flow.bytes,
                    "packets": flow.packets,
                    "duration_ms": flow.duration_ms or 0,
                    "tcp_flags": flow.tcp_flags or 0,
                }
            )

        db.commit()

        logger.info(
            f"Ingested {len(validation.valid_flows)}/{len(batch.flows)} flows, "
            f"batch_id={batch_id}, rejected={validation.rejected_count}"
        )

        return FlowIngestResponse(
            status="accepted",
            flows_received=len(batch.flows),
            flows_accepted=len(validation.valid_flows),
            flows_rejected=validation.rejected_count,
            batch_id=batch_id,
            warnings=validation.warnings
        )

    except Exception as e:
        logger.error(f"Failed to ingest flows: {e}")
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to ingest flows"
        )


@router.get("/stats")
async def get_flow_stats(
    site_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_viewer)
):
    """Get flow ingestion statistics for a site."""
    try:
        result = db.execute(text("""
            SELECT
                COUNT(*) as total_flows,
                COALESCE(SUM(bytes), 0) as total_bytes,
                COALESCE(SUM(packets), 0) as total_packets,
                COUNT(DISTINCT src_ip) as unique_src_ips,
                COUNT(DISTINCT dst_ip) as unique_dst_ips,
                MIN(ts_start) as earliest_flow,
                MAX(ts_end) as latest_flow
            FROM flows_raw
            WHERE site_id = :site_id
            AND ts_start > NOW() - INTERVAL '1 hour'
        """), {"site_id": site_id})

        row = result.fetchone()

        return {
            "site_id": site_id,
            "time_range": {
                "start": row.earliest_flow.isoformat() if row.earliest_flow else None,
                "end": row.latest_flow.isoformat() if row.latest_flow else None
            },
            "stats": {
                "total_flows": row.total_flows,
                "total_bytes": row.total_bytes,
                "total_packets": row.total_packets,
                "unique_src_ips": row.unique_src_ips,
                "unique_dst_ips": row.unique_dst_ips
            }
        }
    except Exception as e:
        logger.error(f"Failed to get flow stats: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )
