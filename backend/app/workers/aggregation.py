"""
Flow aggregation worker - generates 5-minute feature vectors per asset.

This worker reads from flows_raw and generates feature vectors in features_5m
for use by the ML scoring engine.
"""

import logging
import math
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)

# Get database URL
import os
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://netsentinel:netsentinel_dev@localhost:5432/netsentinel")

# Create engine for worker
engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine)


def calculate_entropy(counts: Dict[any, int]) -> float:
    """
    Calculate Shannon entropy from a frequency distribution.

    Args:
        counts: Dictionary mapping values to their counts

    Returns:
        Shannon entropy in bits
    """
    if not counts:
        return 0.0

    total = sum(counts.values())
    if total == 0:
        return 0.0

    entropy = 0.0
    for count in counts.values():
        if count > 0:
            p = count / total
            entropy -= p * math.log2(p)

    return round(entropy, 4)


def get_window_boundaries(reference_time: Optional[datetime] = None) -> Tuple[datetime, datetime]:
    """
    Get the start and end of the most recent complete 5-minute window.

    Args:
        reference_time: Reference time (default: now)

    Returns:
        Tuple of (window_start, window_end)
    """
    if reference_time is None:
        reference_time = datetime.utcnow()

    # Round down to nearest 5 minutes
    minute = (reference_time.minute // 5) * 5
    window_end = reference_time.replace(minute=minute, second=0, microsecond=0)
    window_start = window_end - timedelta(minutes=5)

    return window_start, window_end


def is_business_hours(dt: datetime) -> bool:
    """Check if datetime is during typical business hours (9 AM - 6 PM, Mon-Fri)."""
    return dt.weekday() < 5 and 9 <= dt.hour < 18


@celery_app.task(bind=True, max_retries=3, default_retry_delay=60)
def aggregate_flows(self, site_id: Optional[str] = None, window_start: Optional[str] = None):
    """
    Aggregate flows into 5-minute feature vectors per asset.

    This task is idempotent - it uses UPSERT to handle re-runs without duplicates.

    Args:
        site_id: Optional specific site to process (default: all sites)
        window_start: Optional specific window to process (ISO format string)
    """
    db = SessionLocal()

    try:
        # Determine time window
        if window_start:
            w_start = datetime.fromisoformat(window_start)
            w_end = w_start + timedelta(minutes=5)
        else:
            w_start, w_end = get_window_boundaries()

        logger.info(f"Aggregating flows for window {w_start} to {w_end}")

        # Get sites to process
        if site_id:
            sites = [(site_id,)]
        else:
            result = db.execute(text("SELECT id FROM sites WHERE status = 'active'"))
            sites = result.fetchall()

        for (current_site_id,) in sites:
            try:
                _aggregate_site_flows(db, current_site_id, w_start, w_end)
            except Exception as e:
                logger.error(f"Failed to aggregate site {current_site_id}: {e}")
                continue

        db.commit()
        logger.info(f"Aggregation complete for window {w_start}")

    except Exception as e:
        logger.error(f"Aggregation failed: {e}")
        db.rollback()
        raise self.retry(exc=e)
    finally:
        db.close()


def _aggregate_site_flows(db, site_id: str, window_start: datetime, window_end: datetime):
    """
    Aggregate flows for a single site and time window.

    Args:
        db: Database session
        site_id: Site ID to process
        window_start: Start of time window
        window_end: End of time window
    """
    # Check if already processed (idempotency)
    existing = db.execute(
        text("""
            SELECT COUNT(*) FROM features_5m
            WHERE site_id = :site_id AND window_start = :window_start
        """),
        {"site_id": site_id, "window_start": window_start}
    ).scalar()

    if existing > 0:
        logger.debug(f"Window {window_start} already processed for site {site_id}, skipping")
        return

    # Get all flows for this window
    flows_result = db.execute(
        text("""
            SELECT
                src_ip, dst_ip, src_port, dst_port,
                protocol, bytes, packets, tcp_flags,
                is_internal_src, is_internal_dst
            FROM flows_raw
            WHERE site_id = :site_id
            AND ts_start >= :window_start
            AND ts_start < :window_end
        """),
        {"site_id": site_id, "window_start": window_start, "window_end": window_end}
    )

    flows = flows_result.fetchall()

    if not flows:
        logger.debug(f"No flows for site {site_id} in window {window_start}")
        return

    # Aggregate per internal asset (both as source and destination)
    asset_features = defaultdict(lambda: {
        "flows_in": 0,
        "flows_out": 0,
        "bytes_in": 0,
        "bytes_out": 0,
        "packets_in": 0,
        "packets_out": 0,
        "src_ips": set(),
        "dst_ips": set(),
        "src_ports": set(),
        "dst_ports": set(),
        "dst_port_counts": defaultdict(int),
        "dst_ip_counts": defaultdict(int),
        "src_port_counts": defaultdict(int),
        "internal_dst_count": 0,
        "external_dst_count": 0,
        "internal_src_count": 0,
        "external_src_count": 0,
        "tcp_flows": 0,
        "udp_flows": 0,
        "icmp_flows": 0,
        "other_protocol_flows": 0,
        "flow_durations": [],
        "flow_bytes": [],
        "flow_packets": [],
    })

    # First pass: identify internal IPs and get existing assets
    internal_ips = set()
    result = db.execute(
        text("SELECT ip FROM assets WHERE site_id = :site_id"),
        {"site_id": site_id}
    )
    for (ip,) in result:
        internal_ips.add(str(ip))

    # Also check flows for internal markers
    for flow in flows:
        if flow.is_internal_src:
            internal_ips.add(str(flow.src_ip))
        if flow.is_internal_dst:
            internal_ips.add(str(flow.dst_ip))

    # Second pass: aggregate features
    for flow in flows:
        src_ip = str(flow.src_ip)
        dst_ip = str(flow.dst_ip)
        is_src_internal = src_ip in internal_ips or flow.is_internal_src
        is_dst_internal = dst_ip in internal_ips or flow.is_internal_dst

        # Track outbound traffic from internal source
        if is_src_internal:
            f = asset_features[src_ip]
            f["flows_out"] += 1
            f["bytes_out"] += flow.bytes or 0
            f["packets_out"] += flow.packets or 0
            f["dst_ips"].add(dst_ip)
            f["dst_ports"].add(flow.dst_port)
            f["dst_port_counts"][flow.dst_port] += 1
            f["dst_ip_counts"][dst_ip] += 1

            if is_dst_internal:
                f["internal_dst_count"] += 1
            else:
                f["external_dst_count"] += 1

            # Protocol tracking
            if flow.protocol == 6:
                f["tcp_flows"] += 1
            elif flow.protocol == 17:
                f["udp_flows"] += 1
            elif flow.protocol == 1:
                f["icmp_flows"] += 1
            else:
                f["other_protocol_flows"] += 1

            f["flow_bytes"].append(flow.bytes or 0)
            f["flow_packets"].append(flow.packets or 0)

        # Track inbound traffic to internal destination
        if is_dst_internal:
            f = asset_features[dst_ip]
            f["flows_in"] += 1
            f["bytes_in"] += flow.bytes or 0
            f["packets_in"] += flow.packets or 0
            f["src_ips"].add(src_ip)
            f["src_ports"].add(flow.src_port)
            f["src_port_counts"][flow.src_port] += 1

            if is_src_internal:
                f["internal_src_count"] += 1
            else:
                f["external_src_count"] += 1

    # Insert/update feature vectors
    hour_of_day = window_start.hour
    day_of_week = window_start.weekday()
    is_biz_hours = is_business_hours(window_start)

    for asset_ip, features in asset_features.items():
        # Ensure asset exists
        asset_id = _ensure_asset_exists(db, site_id, asset_ip)

        if not asset_id:
            continue

        # Calculate entropy features
        dst_port_entropy = calculate_entropy(features["dst_port_counts"])
        dst_ip_entropy = calculate_entropy(features["dst_ip_counts"])
        src_port_entropy = calculate_entropy(features["src_port_counts"])

        # Calculate averages
        total_flows = features["flows_in"] + features["flows_out"]
        avg_bytes_per_flow = (
            sum(features["flow_bytes"]) / len(features["flow_bytes"])
            if features["flow_bytes"] else 0
        )
        avg_packets_per_flow = (
            sum(features["flow_packets"]) / len(features["flow_packets"])
            if features["flow_packets"] else 0
        )

        # Calculate internal/external ratio
        total_dst = features["internal_dst_count"] + features["external_dst_count"]
        internal_external_ratio = (
            features["internal_dst_count"] / total_dst
            if total_dst > 0 else 0.5
        )

        # Insert feature vector (UPSERT for idempotency)
        db.execute(
            text("""
                INSERT INTO features_5m (
                    window_start, window_end, site_id, asset_id,
                    flows_in, flows_out, bytes_in, bytes_out,
                    packets_in, packets_out,
                    unique_src_ips, unique_dst_ips,
                    unique_src_ports, unique_dst_ports,
                    internal_dst_count, external_dst_count,
                    internal_src_count, external_src_count,
                    dst_port_entropy, dst_ip_entropy, src_port_entropy,
                    tcp_flows, udp_flows, icmp_flows, other_protocol_flows,
                    avg_bytes_per_flow, avg_packets_per_flow,
                    hour_of_day, day_of_week, is_business_hours,
                    internal_external_ratio
                ) VALUES (
                    :window_start, :window_end, :site_id, :asset_id,
                    :flows_in, :flows_out, :bytes_in, :bytes_out,
                    :packets_in, :packets_out,
                    :unique_src_ips, :unique_dst_ips,
                    :unique_src_ports, :unique_dst_ports,
                    :internal_dst_count, :external_dst_count,
                    :internal_src_count, :external_src_count,
                    :dst_port_entropy, :dst_ip_entropy, :src_port_entropy,
                    :tcp_flows, :udp_flows, :icmp_flows, :other_protocol_flows,
                    :avg_bytes_per_flow, :avg_packets_per_flow,
                    :hour_of_day, :day_of_week, :is_business_hours,
                    :internal_external_ratio
                )
                ON CONFLICT (site_id, asset_id, window_start)
                DO UPDATE SET
                    flows_in = EXCLUDED.flows_in,
                    flows_out = EXCLUDED.flows_out,
                    bytes_in = EXCLUDED.bytes_in,
                    bytes_out = EXCLUDED.bytes_out,
                    packets_in = EXCLUDED.packets_in,
                    packets_out = EXCLUDED.packets_out,
                    unique_src_ips = EXCLUDED.unique_src_ips,
                    unique_dst_ips = EXCLUDED.unique_dst_ips,
                    unique_src_ports = EXCLUDED.unique_src_ports,
                    unique_dst_ports = EXCLUDED.unique_dst_ports,
                    dst_port_entropy = EXCLUDED.dst_port_entropy,
                    dst_ip_entropy = EXCLUDED.dst_ip_entropy,
                    src_port_entropy = EXCLUDED.src_port_entropy
            """),
            {
                "window_start": window_start,
                "window_end": window_end,
                "site_id": site_id,
                "asset_id": asset_id,
                "flows_in": features["flows_in"],
                "flows_out": features["flows_out"],
                "bytes_in": features["bytes_in"],
                "bytes_out": features["bytes_out"],
                "packets_in": features["packets_in"],
                "packets_out": features["packets_out"],
                "unique_src_ips": len(features["src_ips"]),
                "unique_dst_ips": len(features["dst_ips"]),
                "unique_src_ports": len(features["src_ports"]),
                "unique_dst_ports": len(features["dst_ports"]),
                "internal_dst_count": features["internal_dst_count"],
                "external_dst_count": features["external_dst_count"],
                "internal_src_count": features["internal_src_count"],
                "external_src_count": features["external_src_count"],
                "dst_port_entropy": dst_port_entropy,
                "dst_ip_entropy": dst_ip_entropy,
                "src_port_entropy": src_port_entropy,
                "tcp_flows": features["tcp_flows"],
                "udp_flows": features["udp_flows"],
                "icmp_flows": features["icmp_flows"],
                "other_protocol_flows": features["other_protocol_flows"],
                "avg_bytes_per_flow": avg_bytes_per_flow,
                "avg_packets_per_flow": avg_packets_per_flow,
                "hour_of_day": hour_of_day,
                "day_of_week": day_of_week,
                "is_business_hours": is_biz_hours,
                "internal_external_ratio": internal_external_ratio,
            }
        )

    logger.info(f"Aggregated {len(asset_features)} assets for site {site_id}")


def _ensure_asset_exists(db, site_id: str, ip: str) -> Optional[str]:
    """
    Ensure an asset exists in the assets table, creating if necessary.

    Args:
        db: Database session
        site_id: Site ID
        ip: IP address

    Returns:
        Asset ID or None if failed
    """
    try:
        # Check if asset exists
        result = db.execute(
            text("SELECT id FROM assets WHERE site_id = :site_id AND ip = :ip"),
            {"site_id": site_id, "ip": ip}
        )
        row = result.fetchone()

        if row:
            # Update last_seen
            db.execute(
                text("UPDATE assets SET last_seen = NOW() WHERE id = :id"),
                {"id": row.id}
            )
            return str(row.id)

        # Create new asset
        result = db.execute(
            text("""
                INSERT INTO assets (site_id, ip, first_seen, last_seen)
                VALUES (:site_id, :ip, NOW(), NOW())
                RETURNING id
            """),
            {"site_id": site_id, "ip": ip}
        )
        row = result.fetchone()
        return str(row.id) if row else None

    except Exception as e:
        logger.error(f"Failed to ensure asset {ip}: {e}")
        return None


@celery_app.task
def backfill_aggregation(site_id: str, start_time: str, end_time: str):
    """
    Backfill aggregation for a historical time range.

    Args:
        site_id: Site ID to backfill
        start_time: Start time (ISO format)
        end_time: End time (ISO format)
    """
    start = datetime.fromisoformat(start_time)
    end = datetime.fromisoformat(end_time)

    # Round to 5-minute boundaries
    start = start.replace(minute=(start.minute // 5) * 5, second=0, microsecond=0)

    current = start
    while current < end:
        aggregate_flows.delay(site_id=site_id, window_start=current.isoformat())
        current += timedelta(minutes=5)

    logger.info(f"Queued backfill from {start} to {end} for site {site_id}")
