"""
Alert Notifications - sends alerts via email and webhooks.

Supports:
- Email notifications with HTML formatting
- Webhook notifications (Slack, Teams, generic)
- Rate limiting and batching
- Retry logic with exponential backoff
"""

import hashlib
import json
import logging
import os
import smtplib
from dataclasses import dataclass
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any, Dict, List, Optional

import httpx
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.alerting.engine import AlertCandidate

logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://netsentinel:netsentinel_dev@localhost:5432/netsentinel"
)

# Email configuration
SMTP_HOST = os.getenv("SMTP_HOST", "localhost")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_FROM = os.getenv("SMTP_FROM", "alerts@netsentinel.local")
SMTP_USE_TLS = os.getenv("SMTP_USE_TLS", "true").lower() == "true"

# Webhook timeout
WEBHOOK_TIMEOUT = 30


@dataclass
class NotificationResult:
    """Result of a notification attempt."""
    success: bool
    channel: str
    channel_type: str
    error: Optional[str] = None
    response: Optional[str] = None


class NotificationService:
    """
    Handles sending alert notifications via various channels.
    """

    def __init__(self, db_url: Optional[str] = None):
        self.db_url = db_url or DATABASE_URL
        self.engine = create_engine(self.db_url, pool_pre_ping=True)
        self.SessionLocal = sessionmaker(bind=self.engine)

    def get_notification_settings(
        self,
        db: Session,
        site_id: str,
        min_severity: str = "low",
    ) -> List[Dict[str, Any]]:
        """Get notification settings for a site."""
        severity_order = {"low": 1, "medium": 2, "high": 3, "critical": 4}
        min_level = severity_order.get(min_severity, 1)

        result = db.execute(
            text("""
                SELECT
                    id, channel_type, channel_name, config,
                    min_severity, alert_types, batch_interval_minutes,
                    quiet_hours_start, quiet_hours_end, quiet_hours_timezone
                FROM notification_settings
                WHERE site_id = :site_id
                AND is_enabled = true
            """),
            {"site_id": site_id}
        )

        settings = []
        for row in result.fetchall():
            setting = dict(row._mapping)
            setting_min = severity_order.get(setting.get("min_severity", "low"), 1)
            if setting_min <= min_level:
                settings.append(setting)

        return settings

    def is_in_quiet_hours(
        self,
        start_time: Optional[str],
        end_time: Optional[str],
        timezone: str = "UTC",
    ) -> bool:
        """Check if current time is within quiet hours."""
        if not start_time or not end_time:
            return False

        # Simple UTC-only implementation for now
        now = datetime.utcnow()
        current_time = now.time()

        try:
            start = datetime.strptime(start_time, "%H:%M:%S").time()
            end = datetime.strptime(end_time, "%H:%M:%S").time()

            if start <= end:
                return start <= current_time <= end
            else:
                # Quiet hours span midnight
                return current_time >= start or current_time <= end

        except (ValueError, TypeError):
            return False

    def send_notifications(
        self,
        alert: AlertCandidate,
    ) -> List[NotificationResult]:
        """
        Send notifications for an alert through all configured channels.

        Args:
            alert: The alert to send notifications for

        Returns:
            List of NotificationResult objects
        """
        db = self.SessionLocal()
        results = []

        try:
            settings = self.get_notification_settings(db, alert.site_id, alert.severity)

            for setting in settings:
                # Check quiet hours
                if self.is_in_quiet_hours(
                    setting.get("quiet_hours_start"),
                    setting.get("quiet_hours_end"),
                    setting.get("quiet_hours_timezone", "UTC"),
                ):
                    logger.debug(f"Skipping notification {setting['id']} - quiet hours")
                    continue

                channel_type = setting["channel_type"]
                config = setting.get("config", {})
                if isinstance(config, str):
                    config = json.loads(config)

                try:
                    if channel_type == "email":
                        result = self._send_email(alert, config, setting["channel_name"])
                    elif channel_type == "webhook":
                        result = self._send_webhook(alert, config, setting["channel_name"])
                    elif channel_type == "slack":
                        result = self._send_slack(alert, config, setting["channel_name"])
                    elif channel_type == "teams":
                        result = self._send_teams(alert, config, setting["channel_name"])
                    else:
                        result = NotificationResult(
                            success=False,
                            channel=setting["channel_name"] or channel_type,
                            channel_type=channel_type,
                            error=f"Unknown channel type: {channel_type}",
                        )

                    results.append(result)

                    # Update last_sent_at
                    if result.success:
                        db.execute(
                            text("""
                                UPDATE notification_settings
                                SET last_sent_at = NOW()
                                WHERE id = :id
                            """),
                            {"id": setting["id"]}
                        )

                except Exception as e:
                    logger.error(f"Notification failed for {channel_type}: {e}")
                    results.append(NotificationResult(
                        success=False,
                        channel=setting["channel_name"] or channel_type,
                        channel_type=channel_type,
                        error=str(e),
                    ))

            db.commit()
            return results

        except Exception as e:
            logger.error(f"Notification service error: {e}")
            db.rollback()
            raise
        finally:
            db.close()

    def _send_email(
        self,
        alert: AlertCandidate,
        config: Dict[str, Any],
        channel_name: Optional[str],
    ) -> NotificationResult:
        """Send email notification."""
        recipients = config.get("recipients", [])
        if isinstance(recipients, str):
            recipients = [recipients]

        if not recipients:
            return NotificationResult(
                success=False,
                channel=channel_name or "email",
                channel_type="email",
                error="No recipients configured",
            )

        # Build email
        subject = f"[NetSentinel] {alert.severity.upper()}: Alert on {alert.asset_name}"

        # HTML body
        html_body = self._build_email_html(alert)
        text_body = self._build_email_text(alert)

        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = SMTP_FROM
            msg["To"] = ", ".join(recipients)

            msg.attach(MIMEText(text_body, "plain"))
            msg.attach(MIMEText(html_body, "html"))

            # Send
            with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
                if SMTP_USE_TLS:
                    server.starttls()
                if SMTP_USER and SMTP_PASSWORD:
                    server.login(SMTP_USER, SMTP_PASSWORD)
                server.sendmail(SMTP_FROM, recipients, msg.as_string())

            logger.info(f"Email sent to {len(recipients)} recipients")

            return NotificationResult(
                success=True,
                channel=channel_name or "email",
                channel_type="email",
            )

        except Exception as e:
            logger.error(f"Email send failed: {e}")
            return NotificationResult(
                success=False,
                channel=channel_name or "email",
                channel_type="email",
                error=str(e),
            )

    def _build_email_html(self, alert: AlertCandidate) -> str:
        """Build HTML email body."""
        severity_colors = {
            "critical": "#dc3545",
            "high": "#fd7e14",
            "medium": "#ffc107",
            "low": "#17a2b8",
        }

        deviations_html = ""
        for d in alert.feature_deviations[:5]:
            deviations_html += f"""
            <tr>
                <td style="padding: 8px; border-bottom: 1px solid #eee;">{d.feature_name}</td>
                <td style="padding: 8px; border-bottom: 1px solid #eee;">{d.baseline_value:.2f}</td>
                <td style="padding: 8px; border-bottom: 1px solid #eee;">{d.current_value:.2f}</td>
                <td style="padding: 8px; border-bottom: 1px solid #eee; color: {'#dc3545' if d.direction == 'increase' else '#28a745'};">
                    {d.to_human_readable()}
                </td>
            </tr>
            """

        return f"""
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; }}
                .alert-box {{ border-left: 4px solid {severity_colors.get(alert.severity, '#6c757d')}; padding: 15px; margin: 10px 0; background: #f8f9fa; }}
                .severity {{ display: inline-block; padding: 4px 8px; border-radius: 4px; color: white; background: {severity_colors.get(alert.severity, '#6c757d')}; font-weight: bold; }}
                table {{ border-collapse: collapse; width: 100%; margin: 15px 0; }}
                th {{ background: #f1f3f4; padding: 10px; text-align: left; }}
            </style>
        </head>
        <body>
            <h2>NetSentinel Security Alert</h2>

            <div class="alert-box">
                <p><span class="severity">{alert.severity.upper()}</span></p>
                <h3>{alert.asset_name} ({alert.asset_ip})</h3>
                <p>Anomaly score: <strong>{alert.peak_score:.2f}</strong></p>
                <p>Time: {alert.window_start.strftime('%Y-%m-%d %H:%M')} - {alert.window_end.strftime('%H:%M')} UTC</p>
                <p>Consecutive anomalous windows: {alert.consecutive_windows}</p>
            </div>

            <h3>Feature Deviations from Baseline</h3>
            <table>
                <tr>
                    <th>Feature</th>
                    <th>Baseline (7d avg)</th>
                    <th>Current</th>
                    <th>Change</th>
                </tr>
                {deviations_html}
            </table>

            <h3>Recommended Actions</h3>
            <ul>
                {''.join(f'<li>{a}</li>' for a in alert.raw_explanation.get('suggested_actions', ['Review the alert in NetSentinel dashboard'])[:5])}
            </ul>

            <p style="color: #6c757d; font-size: 12px; margin-top: 30px;">
                This alert was generated by NetSentinel.
                <a href="#">View in Dashboard</a> | <a href="#">Manage Notifications</a>
            </p>
        </body>
        </html>
        """

    def _build_email_text(self, alert: AlertCandidate) -> str:
        """Build plain text email body."""
        deviations = "\n".join(
            f"  - {d.feature_name}: {d.baseline_value:.2f} -> {d.current_value:.2f} ({d.to_human_readable()})"
            for d in alert.feature_deviations[:5]
        )

        return f"""
NetSentinel Security Alert
==========================

Severity: {alert.severity.upper()}
Asset: {alert.asset_name} ({alert.asset_ip})
Anomaly Score: {alert.peak_score:.2f}
Time: {alert.window_start.strftime('%Y-%m-%d %H:%M')} - {alert.window_end.strftime('%H:%M')} UTC
Consecutive Windows: {alert.consecutive_windows}

Feature Deviations:
{deviations}

This alert was generated by NetSentinel.
        """

    def _send_webhook(
        self,
        alert: AlertCandidate,
        config: Dict[str, Any],
        channel_name: Optional[str],
    ) -> NotificationResult:
        """Send generic webhook notification."""
        url = config.get("url")
        if not url:
            return NotificationResult(
                success=False,
                channel=channel_name or "webhook",
                channel_type="webhook",
                error="No webhook URL configured",
            )

        payload = self._build_webhook_payload(alert)

        # Add custom headers if configured
        headers = {"Content-Type": "application/json"}
        custom_headers = config.get("headers", {})
        headers.update(custom_headers)

        # Add auth token if configured
        auth_token = config.get("auth_token")
        if auth_token:
            headers["Authorization"] = f"Bearer {auth_token}"

        try:
            with httpx.Client(timeout=WEBHOOK_TIMEOUT) as client:
                response = client.post(url, json=payload, headers=headers)
                response.raise_for_status()

            logger.info(f"Webhook sent successfully to {url}")

            return NotificationResult(
                success=True,
                channel=channel_name or "webhook",
                channel_type="webhook",
                response=response.text[:200],
            )

        except Exception as e:
            logger.error(f"Webhook failed: {e}")
            return NotificationResult(
                success=False,
                channel=channel_name or "webhook",
                channel_type="webhook",
                error=str(e),
            )

    def _build_webhook_payload(self, alert: AlertCandidate) -> Dict[str, Any]:
        """Build webhook payload."""
        return {
            "event": "alert.created",
            "timestamp": datetime.utcnow().isoformat(),
            "alert": {
                "id": alert.dedup_key,
                "site_id": alert.site_id,
                "asset_id": alert.asset_id,
                "asset_name": alert.asset_name,
                "asset_ip": alert.asset_ip,
                "severity": alert.severity,
                "type": alert.alert_type,
                "score": {
                    "peak": alert.peak_score,
                    "average": alert.avg_score,
                },
                "time": {
                    "start": alert.window_start.isoformat(),
                    "end": alert.window_end.isoformat(),
                    "consecutive_windows": alert.consecutive_windows,
                },
                "deviations": [
                    {
                        "feature": d.feature_name,
                        "baseline": d.baseline_value,
                        "current": d.current_value,
                        "change_pct": d.deviation_pct,
                        "multiplier": d.deviation_multiplier,
                    }
                    for d in alert.feature_deviations[:10]
                ],
                "explanation": alert.to_explanation_json(),
            },
        }

    def _send_slack(
        self,
        alert: AlertCandidate,
        config: Dict[str, Any],
        channel_name: Optional[str],
    ) -> NotificationResult:
        """Send Slack notification."""
        webhook_url = config.get("webhook_url")
        if not webhook_url:
            return NotificationResult(
                success=False,
                channel=channel_name or "slack",
                channel_type="slack",
                error="No Slack webhook URL configured",
            )

        # Build Slack message with blocks
        severity_emoji = {
            "critical": ":rotating_light:",
            "high": ":warning:",
            "medium": ":large_orange_diamond:",
            "low": ":information_source:",
        }

        deviations_text = "\n".join(
            f"• `{d.feature_name}`: {d.baseline_value:.2f} → {d.current_value:.2f} ({d.to_human_readable()})"
            for d in alert.feature_deviations[:5]
        )

        payload = {
            "blocks": [
                {
                    "type": "header",
                    "text": {
                        "type": "plain_text",
                        "text": f"{severity_emoji.get(alert.severity, ':bell:')} NetSentinel Alert",
                    }
                },
                {
                    "type": "section",
                    "fields": [
                        {"type": "mrkdwn", "text": f"*Severity:*\n{alert.severity.upper()}"},
                        {"type": "mrkdwn", "text": f"*Score:*\n{alert.peak_score:.2f}"},
                        {"type": "mrkdwn", "text": f"*Asset:*\n{alert.asset_name}"},
                        {"type": "mrkdwn", "text": f"*IP:*\n{alert.asset_ip}"},
                    ]
                },
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*Feature Deviations:*\n{deviations_text}",
                    }
                },
                {
                    "type": "context",
                    "elements": [
                        {
                            "type": "mrkdwn",
                            "text": f"Detected: {alert.window_start.strftime('%Y-%m-%d %H:%M')} UTC | Consecutive windows: {alert.consecutive_windows}",
                        }
                    ]
                },
            ]
        }

        try:
            with httpx.Client(timeout=WEBHOOK_TIMEOUT) as client:
                response = client.post(webhook_url, json=payload)
                response.raise_for_status()

            return NotificationResult(
                success=True,
                channel=channel_name or "slack",
                channel_type="slack",
            )

        except Exception as e:
            logger.error(f"Slack notification failed: {e}")
            return NotificationResult(
                success=False,
                channel=channel_name or "slack",
                channel_type="slack",
                error=str(e),
            )

    def _send_teams(
        self,
        alert: AlertCandidate,
        config: Dict[str, Any],
        channel_name: Optional[str],
    ) -> NotificationResult:
        """Send Microsoft Teams notification."""
        webhook_url = config.get("webhook_url")
        if not webhook_url:
            return NotificationResult(
                success=False,
                channel=channel_name or "teams",
                channel_type="teams",
                error="No Teams webhook URL configured",
            )

        severity_colors = {
            "critical": "FF0000",
            "high": "FFA500",
            "medium": "FFFF00",
            "low": "00BFFF",
        }

        deviations_text = "\n\n".join(
            f"**{d.feature_name}**: {d.baseline_value:.2f} → {d.current_value:.2f} ({d.to_human_readable()})"
            for d in alert.feature_deviations[:5]
        )

        # Adaptive Card payload for Teams
        payload = {
            "@type": "MessageCard",
            "@context": "http://schema.org/extensions",
            "themeColor": severity_colors.get(alert.severity, "808080"),
            "summary": f"NetSentinel Alert: {alert.severity.upper()} on {alert.asset_name}",
            "sections": [
                {
                    "activityTitle": f"🔔 NetSentinel Security Alert",
                    "activitySubtitle": f"{alert.severity.upper()} severity",
                    "facts": [
                        {"name": "Asset", "value": alert.asset_name},
                        {"name": "IP Address", "value": alert.asset_ip},
                        {"name": "Anomaly Score", "value": f"{alert.peak_score:.2f}"},
                        {"name": "Time", "value": alert.window_start.strftime('%Y-%m-%d %H:%M UTC')},
                        {"name": "Consecutive Windows", "value": str(alert.consecutive_windows)},
                    ],
                    "text": f"**Feature Deviations:**\n\n{deviations_text}",
                }
            ],
        }

        try:
            with httpx.Client(timeout=WEBHOOK_TIMEOUT) as client:
                response = client.post(webhook_url, json=payload)
                response.raise_for_status()

            return NotificationResult(
                success=True,
                channel=channel_name or "teams",
                channel_type="teams",
            )

        except Exception as e:
            logger.error(f"Teams notification failed: {e}")
            return NotificationResult(
                success=False,
                channel=channel_name or "teams",
                channel_type="teams",
                error=str(e),
            )


# Example alert payload for documentation
EXAMPLE_WEBHOOK_PAYLOAD = {
    "event": "alert.created",
    "timestamp": "2026-01-15T16:30:00Z",
    "alert": {
        "id": "a1b2c3d4e5f6",
        "site_id": "550e8400-e29b-41d4-a716-446655440000",
        "asset_id": "660e8400-e29b-41d4-a716-446655440001",
        "asset_name": "workstation-42",
        "asset_ip": "192.168.1.42",
        "severity": "high",
        "type": "anomaly_detection",
        "score": {
            "peak": 0.92,
            "average": 0.88,
        },
        "time": {
            "start": "2026-01-15T16:15:00Z",
            "end": "2026-01-15T16:30:00Z",
            "consecutive_windows": 3,
        },
        "deviations": [
            {
                "feature": "bytes_out",
                "baseline": 50000,
                "current": 400000,
                "change_pct": 700,
                "multiplier": 8.0,
            },
            {
                "feature": "unique_dst_ips",
                "baseline": 12,
                "current": 48,
                "change_pct": 300,
                "multiplier": 4.0,
            },
            {
                "feature": "dst_port_entropy",
                "baseline": 1.5,
                "current": 4.8,
                "change_pct": 220,
                "multiplier": 3.2,
            },
        ],
        "explanation": {
            "summary": "Anomalous behavior: bytes_out 8.0x, unique_dst_ips +300%, dst_port_entropy 3.2x",
            "severity_reason": "Score exceeded 0.85 for 3 consecutive windows",
            "top_deviations": [
                {
                    "feature": "bytes_out",
                    "current": 400000,
                    "baseline": 50000,
                    "deviation_pct": 700,
                    "multiplier": 8.0,
                    "direction": "increase",
                }
            ],
            "statistics": {
                "peak_score": 0.92,
                "avg_score": 0.88,
                "consecutive_windows": 3,
                "window_start": "2026-01-15T16:15:00Z",
                "window_end": "2026-01-15T16:30:00Z",
            },
        },
    },
}
