"""
Alert generation worker - creates alerts from anomaly scores.

This worker reads from anomaly_scores_5m and generates alerts.
"""

import logging
import os
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://netsentinel:netsentinel_dev@localhost:5432/netsentinel")
engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine)

# Alert thresholds
ALERT_THRESHOLD_HIGH = 0.85
ALERT_THRESHOLD_MEDIUM = 0.70
ALERT_THRESHOLD_LOW = 0.50


@celery_app.task(bind=True, max_retries=3, default_retry_delay=60)
def generate_alerts(self, site_id: Optional[str] = None):
    """
    Generate alerts from anomaly scores.

    Checks recent scores and creates alerts for anomalies above threshold.

    Args:
        site_id: Optional specific site to process (default: all active sites)
    """
    db = SessionLocal()

    try:
        logger.info("Generating alerts from anomaly scores")

        # Get sites to process
        if site_id:
            sites = [(site_id,)]
        else:
            result = db.execute(text("SELECT id FROM sites WHERE status = 'active'"))
            sites = result.fetchall()

        alerts_created = 0
        for (current_site_id,) in sites:
            try:
                count = _generate_site_alerts(db, current_site_id)
                alerts_created += count
            except Exception as e:
                logger.error(f"Failed to generate alerts for site {current_site_id}: {e}")
                continue

        db.commit()
        logger.info(f"Alert generation complete, created {alerts_created} alerts")

    except Exception as e:
        logger.error(f"Alert generation failed: {e}")
        db.rollback()
        raise self.retry(exc=e)
    finally:
        db.close()


def _generate_site_alerts(db, site_id: str) -> int:
    """
    Generate alerts for a single site.

    Returns:
        Number of alerts created
    """
    # Find high anomaly scores from the last 15 minutes that don't have alerts
    result = db.execute(
        text("""
            SELECT
                s.site_id, s.asset_id, s.window_start,
                s.anomaly_score, s.feature_contributions,
                a.ip as asset_ip, a.hostname, a.custom_name
            FROM anomaly_scores_5m s
            JOIN assets a ON s.asset_id = a.id
            LEFT JOIN alerts al ON
                al.site_id = s.site_id
                AND al.asset_id = s.asset_id
                AND al.start_time = s.window_start
            WHERE s.site_id = :site_id
            AND s.is_anomaly = true
            AND s.window_start > NOW() - INTERVAL '15 minutes'
            AND al.id IS NULL
        """),
        {"site_id": site_id}
    )

    anomalies = result.fetchall()
    alerts_created = 0

    for anomaly in anomalies:
        # Determine severity
        if anomaly.anomaly_score >= ALERT_THRESHOLD_HIGH:
            severity = "high"
        elif anomaly.anomaly_score >= ALERT_THRESHOLD_MEDIUM:
            severity = "medium"
        else:
            severity = "low"

        # Generate title and description
        asset_name = anomaly.custom_name or anomaly.hostname or str(anomaly.asset_ip)
        title = f"Anomalous behavior detected on {asset_name}"
        description = f"Anomaly score: {anomaly.anomaly_score:.2f}"

        # Create alert
        db.execute(
            text("""
                INSERT INTO alerts (
                    site_id, asset_id, alert_type, severity, status,
                    title, description, peak_score, start_time,
                    explanation, created_at
                ) VALUES (
                    :site_id, :asset_id, 'anomaly_detection', :severity, 'open',
                    :title, :description, :score, :start_time,
                    :explanation, NOW()
                )
            """),
            {
                "site_id": anomaly.site_id,
                "asset_id": anomaly.asset_id,
                "severity": severity,
                "title": title,
                "description": description,
                "score": anomaly.anomaly_score,
                "start_time": anomaly.window_start,
                "explanation": anomaly.feature_contributions or "{}",
            }
        )
        alerts_created += 1

    return alerts_created
