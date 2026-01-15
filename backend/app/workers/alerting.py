"""
Alert generation worker - creates alerts from anomaly scores.

Features:
- Threshold-based alerting with persistence rules
- Feature deviation explanations
- Alert deduplication
- Email and webhook notifications
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

# Lazy imports to avoid circular dependencies
_alert_engine = None
_notification_service = None


def get_alert_engine():
    """Get or create the alert engine singleton."""
    global _alert_engine
    if _alert_engine is None:
        from app.alerting.engine import AlertEngine
        _alert_engine = AlertEngine()
    return _alert_engine


def get_notification_service():
    """Get or create the notification service singleton."""
    global _notification_service
    if _notification_service is None:
        from app.alerting.notifications import NotificationService
        _notification_service = NotificationService()
    return _notification_service


@celery_app.task(bind=True, max_retries=3, default_retry_delay=60)
def generate_alerts(self, site_id: Optional[str] = None):
    """
    Generate alerts from anomaly scores using persistence rules.

    Alert Rules:
    - CRITICAL: Score >= 0.95 (single window)
    - HIGH: Score >= 0.85 for 3 consecutive windows
    - MEDIUM: Score >= 0.70 for 5 consecutive windows

    Args:
        site_id: Optional specific site to process (default: all active sites)
    """
    try:
        logger.info("Generating alerts from anomaly scores")

        alert_engine = get_alert_engine()
        notification_service = get_notification_service()

        # Generate alerts
        alerts = alert_engine.generate_alerts(site_id=site_id)

        logger.info(f"Generated {len(alerts)} new alerts")

        # Send notifications for each alert
        for alert in alerts:
            try:
                results = notification_service.send_notifications(alert)
                successful = sum(1 for r in results if r.success)
                logger.info(
                    f"Sent {successful}/{len(results)} notifications for "
                    f"{alert.severity} alert on {alert.asset_name}"
                )
            except Exception as e:
                logger.error(f"Notification failed for alert on {alert.asset_name}: {e}")

        logger.info(f"Alert generation complete, created {len(alerts)} alerts")

    except Exception as e:
        logger.error(f"Alert generation failed: {e}")
        raise self.retry(exc=e)


@celery_app.task(bind=True, max_retries=3, default_retry_delay=300)
def send_alert_notification(
    self,
    alert_id: str,
    site_id: str,
):
    """
    Send notification for a specific alert.

    Args:
        alert_id: Alert ID to notify about
        site_id: Site ID for the alert
    """
    db = SessionLocal()

    try:
        # Get alert details
        result = db.execute(
            text("""
                SELECT
                    al.id, al.site_id, al.asset_id, al.severity,
                    al.title, al.description, al.peak_score, al.avg_score,
                    al.start_time, al.end_time, al.explanation,
                    a.ip as asset_ip, a.hostname, a.custom_name
                FROM alerts al
                JOIN assets a ON al.asset_id = a.id
                WHERE al.id = :alert_id
            """),
            {"alert_id": alert_id}
        )

        row = result.fetchone()
        if not row:
            logger.warning(f"Alert {alert_id} not found")
            return

        # Build AlertCandidate from DB data
        from app.alerting.engine import AlertCandidate, FeatureDeviation
        import json

        explanation = row.explanation
        if isinstance(explanation, str):
            explanation = json.loads(explanation)

        # Extract deviations from explanation
        deviations = []
        for dev in explanation.get("top_deviations", []):
            deviations.append(FeatureDeviation(
                feature_name=dev.get("feature", "unknown"),
                current_value=dev.get("current", 0),
                baseline_value=dev.get("baseline", 0),
                deviation_pct=dev.get("deviation_pct", 0),
                deviation_multiplier=dev.get("multiplier", 1),
                direction=dev.get("direction", "increase"),
            ))

        asset_name = row.custom_name or row.hostname or str(row.asset_ip)

        alert = AlertCandidate(
            site_id=str(row.site_id),
            asset_id=str(row.asset_id),
            asset_name=asset_name,
            asset_ip=str(row.asset_ip),
            severity=row.severity,
            alert_type="anomaly_detection",
            peak_score=row.peak_score,
            avg_score=row.avg_score or row.peak_score,
            window_start=row.start_time,
            window_end=row.end_time or row.start_time + timedelta(minutes=5),
            consecutive_windows=explanation.get("statistics", {}).get("consecutive_windows", 1),
            feature_deviations=deviations,
            raw_explanation=explanation,
        )

        # Send notifications
        notification_service = get_notification_service()
        results = notification_service.send_notifications(alert)

        successful = sum(1 for r in results if r.success)
        logger.info(f"Sent {successful}/{len(results)} notifications for alert {alert_id}")

        # Update alert notification status
        channels = [r.channel_type for r in results if r.success]
        if channels:
            db.execute(
                text("""
                    UPDATE alerts
                    SET notified_at = NOW(),
                        notification_channels = :channels
                    WHERE id = :alert_id
                """),
                {"alert_id": alert_id, "channels": channels}
            )
            db.commit()

    except Exception as e:
        logger.error(f"Failed to send notification for alert {alert_id}: {e}")
        db.rollback()
        raise self.retry(exc=e)
    finally:
        db.close()


@celery_app.task
def cleanup_resolved_alerts(days: int = 30):
    """
    Archive or delete resolved alerts older than N days.

    Args:
        days: Number of days to keep resolved alerts
    """
    db = SessionLocal()

    try:
        result = db.execute(
            text("""
                DELETE FROM alerts
                WHERE status IN ('resolved', 'false_positive')
                AND updated_at < NOW() - INTERVAL ':days days'
                RETURNING id
            """.replace(":days", str(days)))
        )

        deleted = result.rowcount
        db.commit()

        logger.info(f"Cleaned up {deleted} old resolved alerts")

    except Exception as e:
        logger.error(f"Alert cleanup failed: {e}")
        db.rollback()
    finally:
        db.close()


@celery_app.task
def check_alert_escalation():
    """
    Check for alerts that need escalation.

    Escalates alerts that have been open for too long without acknowledgment.
    """
    db = SessionLocal()

    try:
        # Find alerts open for more than 1 hour
        result = db.execute(
            text("""
                UPDATE alerts
                SET severity = CASE
                    WHEN severity = 'low' THEN 'medium'
                    WHEN severity = 'medium' THEN 'high'
                    ELSE severity
                END,
                description = description || ' [AUTO-ESCALATED]'
                WHERE status = 'open'
                AND created_at < NOW() - INTERVAL '1 hour'
                AND severity IN ('low', 'medium')
                RETURNING id, severity
            """)
        )

        escalated = result.fetchall()
        db.commit()

        if escalated:
            logger.info(f"Escalated {len(escalated)} alerts")
            for alert_id, new_severity in escalated:
                logger.info(f"Alert {alert_id} escalated to {new_severity}")

    except Exception as e:
        logger.error(f"Alert escalation check failed: {e}")
        db.rollback()
    finally:
        db.close()
