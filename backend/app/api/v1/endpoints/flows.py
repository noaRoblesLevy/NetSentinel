"""Flow ingestion endpoints."""

import logging
from datetime import datetime
from typing import List, Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db

logger = logging.getLogger(__name__)
settings = get_settings()
router = APIRouter()


class FlowRecord(BaseModel):
    """Single flow record from collector."""
    ts_start: datetime
    ts_end: datetime
    src_ip: str
    dst_ip: str
    src_port: int = 0
    dst_port: int = 0
    protocol: int
    bytes: int = 0
    packets: int = 0
    tcp_flags: Optional[int] = None
    duration_ms: Optional[int] = None


class FlowBatch(BaseModel):
    """Batch of flow records."""
    site_id: str
    exporter_id: str
    flows: List[FlowRecord]
    batch_id: Optional[str] = None
    timestamp: Optional[datetime] = None


class FlowIngestResponse(BaseModel):
    """Response for flow ingestion."""
    status: str
    flows_received: int
    batch_id: str


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
    """
    # Validate collector API key
    if settings.collector_api_key and x_collector_key != settings.collector_api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid collector API key"
        )

    if not batch.flows:
        return FlowIngestResponse(
            status="accepted",
            flows_received=0,
            batch_id=batch.batch_id or str(uuid4())
        )

    batch_id = batch.batch_id or str(uuid4())

    try:
        # Build bulk insert query
        values = []
        for flow in batch.flows:
            values.append(f"""(
                '{flow.ts_start.isoformat()}',
                '{flow.ts_end.isoformat()}',
                '{batch.site_id}',
                '{batch.exporter_id}',
                '{flow.src_ip}',
                '{flow.dst_ip}',
                {flow.src_port},
                {flow.dst_port},
                {flow.protocol},
                {flow.bytes},
                {flow.packets},
                {flow.duration_ms or 0},
                {flow.tcp_flags or 0}
            )""")

        if values:
            query = f"""
                INSERT INTO flows_raw (
                    ts_start, ts_end, site_id, exporter_id,
                    src_ip, dst_ip, src_port, dst_port,
                    protocol, bytes, packets, duration_ms, tcp_flags
                ) VALUES {','.join(values)}
            """
            db.execute(text(query))
            db.commit()

        logger.info(f"Ingested {len(batch.flows)} flows, batch_id={batch_id}")

        return FlowIngestResponse(
            status="accepted",
            flows_received=len(batch.flows),
            batch_id=batch_id
        )

    except Exception as e:
        logger.error(f"Failed to ingest flows: {e}")
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to ingest flows: {str(e)}"
        )


@router.get("/stats")
async def get_flow_stats(
    site_id: str,
    db: Session = Depends(get_db)
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
